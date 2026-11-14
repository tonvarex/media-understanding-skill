#!/usr/bin/env python3
"""Ask a multimodal model about images, PDFs, a video or audio file, or a video link; get text back."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import base64
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

from download import is_url, is_youtube, local_input
from media import (AUDIO_BITRATE, Chunk, MediaInfo, Window, audio_chunks, convert_image, extract_frames,
                   ffmpeg, media_kind, probe, resolve_window, sample_times, scale_filter)
from openrouter import api_key, post_json
from util import clock, configure_stdio, fail, log, require_tools, scratch_dir

DEFAULT_MODEL = os.environ.get("MUS_MODEL") or "google/gemini-4-hydrogen"
AGENTIC_MAX_MB = 14
IMAGE_MAX_SIDE = 2048
IMAGE_MAX_BYTES = 4_000_000
DOCUMENT_MAX_BYTES = 30_000_000
IMAGE_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
              ".webp": "image/webp", ".gif": "image/gif"}

LENGTH_RULE = ("Reply with the final answer only, in the language of the question and in the length and "
               "format it asks for: no preamble, no description of your process, no padding.")

INSTRUCTIONS = {
    "files": "Examine the attached image(s) and document(s) and answer the question. Read visible text "
             "exactly and say which parts are unreadable. Do not invent details that are not present.",
    "video": "You are analysing a video (picture and sound). Describe what you SEE and what you HEAR "
             "(speech, music, sounds) separately, and do not invent anything absent from the clip. "
             "Cite moments as MM:SS relative to the start of this clip.",
    "frames": "These are frames sampled from a video in chronological order, each preceded by its "
              "timestamp. Base the answer only on what is visible and cite timestamps.",
    "audio": "You are listening to an audio recording. Cover speech (quote it in its original "
             "language), music, sounds and tone as far as the question needs, and do not invent "
             "anything absent. Cite moments as MM:SS relative to the start of this clip.",
}


@dataclass(frozen=True)
class Source:
    kind: str
    path: Path | None = None
    url: str | None = None


@dataclass(frozen=True)
class Job:
    kind: str
    header: str
    size: int
    build: Callable[[], list[dict]]


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def data_url(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{b64(path)}"


def text_part(text: str) -> dict:
    return {"type": "text", "text": text}


def image_part(path: Path, mime: str = "image/jpeg") -> dict:
    return {"type": "image_url", "image_url": {"url": data_url(path, mime)}}


def document_part(path: Path) -> dict:
    return {"type": "file", "file": {"filename": path.name, "file_data": data_url(path, "application/pdf")}}


def video_part(url: str, processing: str | None) -> dict:
    return {"type": "video_url", "video_url": {"url": url, **({"processing": processing} if processing else {})}}


def audio_part(path: Path) -> dict:
    return {"type": "input_audio", "input_audio": {"data": b64(path), "format": "mp3"}}


def user_text(question: str, note: str = "") -> str:
    return "\n".join(filter(None, [note, f"Question: {question}"]))


def part_header(number: int, total: int, offset: float) -> str:
    if total == 1 and not offset:
        return ""
    label = f"PART {number}/{total}" if total > 1 else "TRIMMED CLIP"
    return f"=== {label} (starts at {clock(offset)} in the full media; times below are relative to it) ==="


def part_note(number: int, total: int) -> str:
    if total == 1:
        return ""
    return f"This is part {number} of {total} of a longer recording; answer only about this part."


def needs_local_file(args: argparse.Namespace) -> bool:
    return bool(args.frames) or args.start is not None or args.end is not None


def resolve_sources(inputs: list[str], workdir: Path, local_only: bool) -> list[Source]:
    sources = []
    for value in inputs:
        if not local_only and is_url(value) and is_youtube(value):
            sources.append(Source("youtube", url=value))
        else:
            path = local_input(value, workdir)
            sources.append(Source(media_kind(path), path))
    return sources


def prepare_image(path: Path, workdir: Path, index: int) -> tuple[Path, str]:
    extension = path.suffix.lower()
    if extension in IMAGE_MIME and path.stat().st_size <= IMAGE_MAX_BYTES:
        return path, IMAGE_MIME[extension]
    converted = workdir / f"image_{index}.jpg"
    convert_image(path, converted, IMAGE_MAX_SIDE)
    return converted, "image/jpeg"


def attachment_parts(question: str, items: list[tuple[str, Path, str]]) -> list[dict]:
    parts = [text_part(user_text(question))]
    for number, (kind, path, mime) in enumerate(items, 1):
        label = "Image" if kind == "image" else "Document"
        parts += [text_part(f"{label} {number}:"),
                  image_part(path, mime) if kind == "image" else document_part(path)]
    return parts


def attachment_job(sources: list[Source], question: str, workdir: Path) -> Job:
    items = []
    for index, source in enumerate(sources):
        if source.kind == "image":
            path, mime = prepare_image(source.path, workdir, index)
        else:
            path, mime = source.path, "application/pdf"
            if path.stat().st_size > DOCUMENT_MAX_BYTES:
                fail(f"{path.name} is larger than {DOCUMENT_MAX_BYTES // 1_000_000} MB: split the PDF first")
        items.append((source.kind, path, mime))
    return Job("files", "", sum(path.stat().st_size for _, path, _ in items),
               partial(attachment_parts, question, items))


def frame_parts(question: str, times: list[float], frames: list[Path]) -> list[dict]:
    parts = [text_part(user_text(question))]
    for moment, frame in zip(times, frames):
        parts += [text_part(f"t={moment:.2f}s"), image_part(frame)]
    return parts


def frame_job(source: Path, question: str, window: Window, info: MediaInfo,
              args: argparse.Namespace, workdir: Path) -> Job:
    times = sample_times(window, args.frames, info.duration)
    if len(times) > args.max_frames:
        fail(f"{len(times)} frames exceed --max-frames {args.max_frames}: "
             "raise the step or narrow --start/--end")
    log(f"Extracting {len(times)} frames ...")
    frames = extract_frames(source, times, workdir, args.height)
    return Job("frames", "", sum(frame.stat().st_size for frame in frames),
               partial(frame_parts, question, times, frames))


def encode_video(source: Path, destination: Path, window: Window, source_fps: float,
                 args: argparse.Namespace) -> None:
    filters = [scale_filter(args.height)] + ([f"fps={args.fps}"] if args.fps else [])
    ffmpeg(*window.trim(), "-i", source, "-vf", ",".join(filters),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", args.crf, "-pix_fmt", "yuv420p",
           "-g", int((args.fps or source_fps or 30) * 2), "-c:a", "aac", "-b:a", "48k", "-ac", 1,
           "-movflags", "+faststart", destination)


def split_video(source: Path, directory: Path, seconds: float) -> list[Path]:
    directory.mkdir()
    ffmpeg("-i", source, "-c", "copy", "-f", "segment", "-segment_time", f"{seconds:.2f}",
           "-reset_timestamps", 1, directory / "part_%03d.mp4")
    return sorted(directory.glob("part_*.mp4"))


def video_chunks(source: Path, window: Window, info: MediaInfo, args: argparse.Namespace,
                 workdir: Path) -> list[Chunk]:
    log(f"Compressing {clock(window.length)} of video (long files take a few minutes) ...")
    encoded = workdir / "video.mp4"
    encode_video(source, encoded, window, info.fps, args)
    duration = probe(encoded).duration
    count = max(1, math.ceil(encoded.stat().st_size / 1e6 / args.max_mb),
                math.ceil(duration / (args.max_min * 60)))
    if count == 1:
        return [Chunk(encoded, 0.0, duration)]
    chunks, offset = [], 0.0
    for path in split_video(encoded, workdir / "parts", duration / count + 1):
        length = probe(path).duration
        chunks.append(Chunk(path, offset, offset + length))
        offset += length
    return chunks


def media_parts(kind: str, path: Path, text: str, processing: str | None) -> list[dict]:
    media = audio_part(path) if kind == "audio" else video_part(data_url(path, "video/mp4"), processing)
    return [text_part(text), media]


def chunk_jobs(kind: str, chunks: list[Chunk], window: Window, question: str,
               processing: str | None) -> list[Job]:
    total = len(chunks)
    return [Job(kind, part_header(number, total, window.start + chunk.start), chunk.path.stat().st_size,
                partial(media_parts, kind, chunk.path, user_text(question, part_note(number, total)),
                        processing))
            for number, chunk in enumerate(chunks, 1)]


def youtube_job(url: str, question: str, args: argparse.Namespace) -> Job:
    parts = [text_part(user_text(question)), video_part(url, args.processing)]
    return Job("video", "", 0, lambda: parts)


def build_jobs(args: argparse.Namespace, sources: list[Source], workdir: Path) -> list[Job]:
    if all(source.kind in {"image", "document"} for source in sources):
        return [attachment_job(sources, args.question, workdir)]
    if len(sources) != 1:
        fail("pass any number of images and PDFs, or exactly one video, audio file or video link")

    source = sources[0]
    if source.kind == "youtube":
        return [youtube_job(source.url, args.question, args)]
    info = probe(source.path)
    kind = "video" if source.kind == "video" and info.has_video else "audio"
    if args.frames and kind != "video":
        fail("--frames only applies to video")
    window = resolve_window(args.start, args.end, info.duration)
    if args.frames:
        return [frame_job(source.path, args.question, window, info, args, workdir)]
    if kind == "video":
        chunks = video_chunks(source.path, window, info, args, workdir)
    else:
        log("Extracting audio ...")
        target = min(args.max_min * 60, args.max_mb * 8e6 / AUDIO_BITRATE)
        chunks = audio_chunks(source.path, workdir, window, target)
    return chunk_jobs(kind, chunks, window, args.question, args.processing)


def run_job(number: int, total: int, job: Job, model: str, key: str) -> tuple[str, dict]:
    started = time.time()
    response = post_json("chat/completions", {
        "model": model,
        "messages": [{"role": "system", "content": f"{INSTRUCTIONS[job.kind]}\n{LENGTH_RULE}"},
                     {"role": "user", "content": job.build()}],
    }, key)
    log(f"  request {number}/{total} done in {time.time() - started:.0f}s")
    choice = (response.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content") or "").strip()
    reason = choice.get("finish_reason") or "unknown"
    return text or f"(empty answer, finish reason: {reason})", response.get("usage") or {}


def usage_summary(model: str, usages: list[dict]) -> str:
    def total(field: str) -> float:
        return sum(float(usage.get(field) or 0) for usage in usages)

    return (f"[{model}: {total('prompt_tokens'):.0f} input / {total('completion_tokens'):.0f} "
            f"output tokens, cost ${total('cost'):.4f}]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+",
                        help="image/PDF files or links, or one video or audio file or link (YouTube, TikTok, ...)")
    parser.add_argument("-q", "--question", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="default: $MUS_MODEL or %(default)s")
    parser.add_argument("--start", type=float, help="trim start, seconds")
    parser.add_argument("--end", type=float, help="trim end, seconds")
    parser.add_argument("--dry-run", action="store_true", help="prepare the media, print the plan, send nothing")

    video = parser.add_argument_group("video")
    video.add_argument("--frames", type=float, metavar="STEP",
                       help="send frames every STEP seconds as images instead of the video")
    video.add_argument("--max-frames", type=int, default=48)
    video.add_argument("--height", type=int, default=480, help="short side in px, 0 keeps the source")
    video.add_argument("--fps", type=int, default=8, help="0 keeps the source fps")
    video.add_argument("--crf", type=int, default=30, help="x264 quality, lower is better")
    video.add_argument("--processing", choices=["agentic", "static"],
                       help="Gemini video mode; routes to Google AI Studio (20 MB request limit)")

    limits = parser.add_argument_group("limits")
    limits.add_argument("--max-mb", type=float, default=30, help="largest part sent in one request")
    limits.add_argument("--max-min", type=float, default=30, help="longest part in minutes")
    limits.add_argument("--parallel", type=int, default=3, help="concurrent requests")

    args = parser.parse_args()
    if not args.question.strip():
        fail("the question is empty")
    if args.processing:
        args.max_mb = min(args.max_mb, AGENTIC_MAX_MB)
    return args


def main() -> None:
    configure_stdio()
    args = parse_args()
    require_tools("ffmpeg", "ffprobe")
    key = None if args.dry_run else api_key()

    with scratch_dir("media_ask_") as workdir:
        jobs = build_jobs(args, resolve_sources(args.inputs, workdir, needs_local_file(args)), workdir)
        if args.dry_run:
            for number, job in enumerate(jobs, 1):
                print(f"part {number}/{len(jobs)}: {job.size / 1e6:.1f} MB {job.header}".rstrip())
            return
        log(f"Sending {len(jobs)} request(s) to {args.model} ...")
        with ThreadPoolExecutor(max(1, args.parallel)) as pool:
            futures = [pool.submit(run_job, number, len(jobs), job, args.model, key)
                       for number, job in enumerate(jobs, 1)]
            results = [future.result() for future in futures]

    for job, (text, _) in zip(jobs, results):
        if job.header:
            print(job.header)
        print(f"{text}\n")
    log(usage_summary(args.model, [usage for _, usage in results]))


if __name__ == "__main__":
    main()
