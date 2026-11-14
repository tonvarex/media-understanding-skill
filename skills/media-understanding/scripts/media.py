"""ffmpeg and ffprobe wrappers: probing, time windows, frame extraction, audio preparation."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import NamedTuple

from util import fail

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg", ".wmv", ".flv", ".ts"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".wma", ".aiff"}
DOCUMENT_EXTENSIONS = {".pdf"}
ANIMATED_IMAGE_EXTENSIONS = {".gif", ".webp", ".apng"}
ANIMATION_MIN_SECONDS = 0.2

AUDIO_BITRATE = 48_000
SILENCE_FILTER = "silencedetect=noise=-35dB:d=0.35"
WORKERS = min(8, os.cpu_count() or 4)


class Window(NamedTuple):
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start

    def trim(self) -> list[str]:
        return ["-ss", f"{self.start:.3f}", "-t", f"{self.length:.3f}"]


class Chunk(NamedTuple):
    path: Path
    start: float
    end: float


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_video: bool
    has_audio: bool


def run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")


def ffmpeg(*args: object) -> None:
    result = run(["ffmpeg", "-y", "-v", "error", *map(str, args)])
    if result.returncode:
        fail(f"ffmpeg failed: {result.stderr.strip()[-400:]}")


def _frame_rate(text: str) -> float:
    try:
        return float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path, strict: bool = True) -> MediaInfo | None:
    result = run(["ffprobe", "-v", "error", "-print_format", "json",
                  "-show_format", "-show_streams", str(path)])
    if result.returncode:
        if strict:
            fail(f"cannot read {path.name} as media: {result.stderr.strip()[:300]}")
        return None
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    return MediaInfo(
        duration=float(data.get("format", {}).get("duration") or 0),
        width=video["width"] if video else 0,
        height=video["height"] if video else 0,
        fps=_frame_rate(video.get("avg_frame_rate", "")) if video else 0.0,
        has_video=video is not None,
        has_audio=any(s["codec_type"] == "audio" for s in streams),
    )


def media_kind(path: Path) -> str:
    extension = path.suffix.lower()
    if extension in DOCUMENT_EXTENSIONS:
        return "document"
    if extension in ANIMATED_IMAGE_EXTENSIONS and probe(path).duration > ANIMATION_MIN_SECONDS:
        return "video"
    for kind, extensions in (("image", IMAGE_EXTENSIONS), ("video", VIDEO_EXTENSIONS),
                             ("audio", AUDIO_EXTENSIONS)):
        if extension in extensions:
            return kind
    info = probe(path, strict=False)
    if info and info.has_video:
        return "video" if info.duration else "image"
    if info and info.has_audio:
        return "audio"
    fail(f"{path.name}: unsupported file (supported: images, PDF, video, audio)")


def resolve_window(start: float | None, end: float | None, duration: float) -> Window:
    window = Window(max(0.0, start or 0.0), min(end or duration, duration))
    if window.length <= 0:
        fail("empty time range: check --start and --end")
    return window


def scale_filter(short_side: int) -> str:
    """Scale so the short side is at most `short_side` (0 keeps the size); dimensions stay even for x264."""
    if not short_side:
        return "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    return (f"scale='if(gt(iw,ih),-2,trunc(min({short_side},iw)/2)*2)':"
            f"'if(gt(iw,ih),trunc(min({short_side},ih)/2)*2,-2)'")


def convert_image(source: Path, destination: Path, max_side: int) -> None:
    fit = f"scale='min({max_side},iw)':'min({max_side},ih)':force_original_aspect_ratio=decrease"
    attempts = [["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vf", fit,
                 "-frames:v", "1", "-q:v", "3", str(destination)]]
    if shutil.which("sips"):
        attempts.append(["sips", "-s", "format", "jpeg", "-Z", str(max_side), str(source),
                         "--out", str(destination)])
    for command in attempts:
        if run(command).returncode == 0 and destination.exists():
            return
    fail(f"cannot convert {source.name} to JPEG (HEIC needs ffmpeg built with libheif, or macOS); "
         "convert it to JPEG or PNG first")


def sample_times(window: Window, step: float, duration: float) -> list[float]:
    last_frame = max(duration - 0.1, 0.0)
    count = int((window.length - 1e-6) // step) + 1
    return [min(window.start + index * step, last_frame) for index in range(count)]


def extract_frames(video: Path, times: list[float], directory: Path, short_side: int) -> list[Path]:
    paths = [directory / f"frame_{index:05d}.jpg" for index in range(len(times))]

    def grab(index: int) -> None:
        ffmpeg("-ss", f"{times[index]:.3f}", "-i", video, "-frames:v", 1,
               "-vf", scale_filter(short_side), "-q:v", 3, paths[index])

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(grab, range(len(times))))
    return paths


def encode_audio(source: Path, destination: Path, window: Window) -> list[float]:
    """Encode to speech-grade mono mp3 and return the midpoints of the pauses found on the way."""
    result = run(["ffmpeg", "-y", "-nostats", "-v", "info", *window.trim(), "-i", str(source),
                  "-vn", "-ac", "1", "-ar", "16000", "-af", SILENCE_FILTER,
                  "-c:a", "libmp3lame", "-b:a", str(AUDIO_BITRATE), str(destination)])
    if result.returncode:
        fail(f"ffmpeg failed: {result.stderr.strip()[-400:]}")
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", result.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", result.stderr)]
    return [(begin + finish) / 2 for begin, finish in zip(starts, ends)]


def plan_cuts(total: float, pauses: list[float], target: float) -> list[tuple[float, float]]:
    cuts, position = [], 0.0
    while total - position > target * 1.25:
        candidates = [pause for pause in pauses if position + target / 2 <= pause <= position + target]
        cut = max(candidates, default=position + target)
        cuts.append((position, cut))
        position = cut
    return cuts + [(position, total)]


def audio_chunks(source: Path, directory: Path, window: Window, target_seconds: float) -> list[Chunk]:
    full = directory / "audio.mp3"
    pauses = encode_audio(source, full, window)
    cuts = plan_cuts(window.length, pauses, target_seconds)
    if len(cuts) == 1:
        return [Chunk(full, 0.0, window.length)]
    chunks = []
    for index, (start, end) in enumerate(cuts):
        path = directory / f"chunk_{index:03d}.mp3"
        ffmpeg(*Window(start, end).trim(), "-i", full, "-c", "copy", path)
        chunks.append(Chunk(path, start, end))
    return chunks
