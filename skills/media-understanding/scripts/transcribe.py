#!/usr/bin/env python3
"""Word-level speech transcription of a video or audio file (or link) via OpenRouter Whisper."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import base64
import json
import re
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import NamedTuple

from download import local_input
from media import Chunk, Window, audio_chunks, probe
from openrouter import api_key, post_json
from util import clock, configure_stdio, fail, log, require_tools, scratch_dir

DEFAULT_MODEL = "openai/whisper-large-v3"
UPLOAD_LIMIT_BYTES = 24 * 1024 * 1024
SENTENCE_END = re.compile(r"[.!?…。！？]$")
ATTEMPTS = 3


class Word(NamedTuple):
    text: str
    start: float
    end: float


def transcribe_chunk(key: str, chunk: Chunk, model: str, language: str) -> dict:
    raw = chunk.path.read_bytes()
    if len(raw) > UPLOAD_LIMIT_BYTES:
        fail(f"{chunk.path.name} exceeds the upload limit: lower --chunk")
    payload = {
        "model": model,
        "input_audio": {"data": base64.b64encode(raw).decode(), "format": "mp3"},
        "response_format": "verbose_json",
        "timestamp_granularities": ["word"],
    }
    if language != "auto":
        payload["language"] = language
    response = {}
    for _ in range(ATTEMPTS):
        response = post_json("audio/transcriptions", payload, key, timeout=120)
        if response.get("words") or not (response.get("text") or "").strip():
            break
    return response


def merge(chunks: list[Chunk], responses: list[dict]) -> tuple[list[Word], list[tuple[float, str]]]:
    words, untimed = [], []
    for chunk, response in zip(chunks, responses):
        timed = [w for w in response.get("words") or [] if (w.get("word") or "").strip()]
        text = (response.get("text") or "").strip()
        if text and not timed:
            untimed.append((chunk.start, text))
        words += [Word(w["word"].strip(), round(w["start"] + chunk.start, 3), round(w["end"] + chunk.start, 3))
                  for w in timed]
    return words, untimed


def group_phrases(words: list[Word], max_gap: float = 0.7, max_chars: int = 90) -> list[list[Word]]:
    phrases: list[list[Word]] = []
    for word in words:
        current = phrases[-1] if phrases else None
        if current is None or (word.start - current[-1].end > max_gap
                               or sum(len(w.text) + 1 for w in current) > max_chars
                               or SENTENCE_END.search(current[-1].text)):
            phrases.append([])
        phrases[-1].append(word)
    return phrases


def render(phrases: list[list[Word]], untimed: list[tuple[float, str]]) -> list[str]:
    entries = [(p[0].start, f"[{clock(p[0].start)}] {' '.join(w.text for w in p)}") for p in phrases]
    entries += [(start, f"[{clock(start)}, no word timestamps] {text}") for start, text in untimed]
    return [line for _, line in sorted(entries)]


def srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def save(directory: Path, model: str, words: list[Word], phrases: list[list[Word]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "transcript.json").write_text(json.dumps(
        {"model": model, "words": [word._asdict() for word in words]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (directory / "transcript.srt").write_text("".join(
        f"{number}\n{srt_time(p[0].start)} --> {srt_time(p[-1].end)}\n{' '.join(w.text for w in p)}\n\n"
        for number, p in enumerate(phrases, 1)), encoding="utf-8")


def main() -> None:
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="audio or video file, or a link (file, YouTube, TikTok, ...)")
    parser.add_argument("--lang", default="auto", help="ISO code such as en or ru; auto detects")
    parser.add_argument("--chunk", type=float, default=240, help="target chunk length in seconds")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--parallel", type=int, default=3, help="concurrent requests")
    parser.add_argument("--out", type=Path, help="also save transcript.json and transcript.srt here")
    args = parser.parse_args()

    require_tools("ffmpeg", "ffprobe")
    key = api_key()

    with scratch_dir("media_transcribe_") as workdir:
        source = local_input(args.input, workdir, audio_only=True)
        info = probe(source)
        if not info.has_audio:
            fail("the file has no audio track")
        log(f"Extracting audio ({clock(info.duration)}) ...")
        chunks = audio_chunks(source, workdir, Window(0.0, info.duration), args.chunk)
        log(f"Transcribing {len(chunks)} chunk(s) ...")
        with ThreadPoolExecutor(max(1, args.parallel)) as pool:
            responses = list(pool.map(
                partial(transcribe_chunk, key, model=args.model, language=args.lang), chunks))

    words, untimed = merge(chunks, responses)
    phrases = group_phrases(words)
    if args.out:
        save(args.out, args.model, words, phrases)
    print(f"=== TRANSCRIPT ({len(words)} words, {clock(info.duration)}) ===")
    print("\n".join(render(phrases, untimed)))


if __name__ == "__main__":
    main()
