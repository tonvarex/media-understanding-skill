#!/usr/bin/env python3
"""Timestamped contact sheets of a video, for models that can view images."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import re
import tempfile
from pathlib import Path

from media import MediaInfo, Window, extract_frames, probe, resolve_window, run, sample_times, scale_filter
from util import clock, configure_stdio, fail, require_tools, scratch_dir

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    fail("Pillow is required: pip install pillow")

FONT_CANDIDATES = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)


def scene_frames(video: Path, window: Window, threshold: float, height: int,
                 directory: Path) -> tuple[list[Path], list[float]]:
    selection = f"select='eq(n\\,0)+gt(scene\\,{threshold})',showinfo,{scale_filter(height)}"
    result = run(["ffmpeg", "-y", "-v", "info", *window.trim(), "-i", str(video), "-vf", selection,
                  "-fps_mode", "vfr", "-q:v", "3", str(directory / "scene_%05d.jpg")])
    if result.returncode:
        fail(f"ffmpeg failed: {result.stderr.strip()[-400:]}")
    frames = sorted(directory.glob("scene_*.jpg"))
    times = [window.start + float(t) for t in re.findall(r"pts_time:([\d.]+)", result.stderr)]
    return frames, times[:len(frames)]


def uniform_frames(video: Path, window: Window, info: MediaInfo, args: argparse.Namespace,
                   directory: Path) -> tuple[list[Path], list[float]]:
    count = args.count or int(min(48, max(12, window.length / 3)))
    times = sample_times(window, max(args.every or window.length / count, 0.1), info.duration)
    return extract_frames(video, times, directory, args.height), times


def load_font(size: int) -> ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def make_sheet(frames: list[Path], times: list[float], columns: int, font: ImageFont.ImageFont) -> Image.Image:
    images = [Image.open(frame).convert("RGB") for frame in frames]
    width, height = images[0].size
    rows = -(-len(images) // columns)
    sheet = Image.new("RGB", (columns * width, rows * height), "black")
    draw = ImageDraw.Draw(sheet)
    for index, (image, moment) in enumerate(zip(images, times)):
        x, y = (index % columns) * width, (index // columns) * height
        sheet.paste(image, (x, y))
        label = clock(moment, 1)
        box = draw.textbbox((0, 0), label, font=font)
        draw.rectangle([x, y, x + box[2] + 8, y + box[3] + 8], fill="black")
        draw.text((x + 4, y + 4 - box[1] // 2), label, fill="yellow", font=font)
    return sheet


def write_sheets(frames: list[Path], times: list[float], args: argparse.Namespace, out: Path) -> list[str]:
    font = load_font(max(14, args.height // 14))
    per_sheet = args.cols * args.rows
    lines = []
    for number, begin in enumerate(range(0, len(frames), per_sheet), 1):
        batch = slice(begin, begin + per_sheet)
        path = out / f"sheet_{number:02d}.jpg"
        make_sheet(frames[batch], times[batch], args.cols, font).save(path, quality=85)
        lines.append(f"{path}  {clock(times[batch][0], 1)} - {clock(times[batch][-1], 1)}")
    return lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--count", type=int, help="evenly spaced frames (default: 12 to 48 by length)")
    mode.add_argument("--every", type=float, metavar="SECONDS", help="one frame per interval")
    mode.add_argument("--scene", type=float, nargs="?", const=0.3, metavar="THRESHOLD",
                      help="frames at scene changes, threshold 0..1")
    parser.add_argument("--start", type=float, help="seconds")
    parser.add_argument("--end", type=float, help="seconds")
    parser.add_argument("--height", type=int, default=360, help="frame short side in px")
    parser.add_argument("--cols", type=int, default=4)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--out", type=Path, help="output directory (default: a new temp directory)")
    args = parser.parse_args()
    if not args.video.is_file():
        fail(f"no such file: {args.video}")
    return args


def main() -> None:
    configure_stdio()
    args = parse_args()
    require_tools("ffmpeg", "ffprobe")
    info = probe(args.video)
    if not info.has_video:
        fail("the file has no video track")
    window = resolve_window(args.start, args.end, info.duration)
    out = args.out or Path(tempfile.mkdtemp(prefix="media_frames_"))
    out.mkdir(parents=True, exist_ok=True)

    with scratch_dir("media_frames_work_") as workdir:
        if args.scene is not None:
            frames, times = scene_frames(args.video, window, args.scene, args.height, workdir)
        else:
            frames, times = uniform_frames(args.video, window, info, args, workdir)
        if not frames:
            fail("no frames were produced: check the range")
        sheets = write_sheets(frames, times, args, out)

    print(f"Video: {clock(info.duration)}, {info.width}x{info.height}, {info.fps:.0f} fps, "
          f"audio: {'yes' if info.has_audio else 'no'}")
    print("\n".join(sheets))


if __name__ == "__main__":
    main()
