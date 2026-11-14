#!/usr/bin/env python3
"""Check that everything the skill needs is installed and configured, and say how to fix what is not."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from ask import DEFAULT_MODEL
from download import YTDLP_HELP, ytdlp_command
from media import run
from openrouter import GENERIC_KEY_ENV, KEY_ENV, get_json
from util import configure_stdio, scratch_dir

ENCODERS = ("libx264", "aac", "libmp3lame")
FFMPEG_HELP = "install ffmpeg: macOS `brew install ffmpeg`, Linux `apt install ffmpeg`, Windows `winget install ffmpeg`"


def report(ok: bool, message: str, fix: str = "") -> bool:
    print(f"[{'ok' if ok else 'FAIL'}] {message}" + (f"\n       fix: {fix}" if fix and not ok else ""))
    return ok


def check_python() -> bool:
    version = ".".join(map(str, sys.version_info[:3]))
    return report(sys.version_info >= (3, 9), f"Python {version}", "install Python 3.9 or newer")


def check_ffmpeg() -> bool:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return report(False, "ffmpeg and ffprobe", FFMPEG_HELP)
    encoders = run(["ffmpeg", "-hide_banner", "-encoders"]).stdout
    filters = run(["ffmpeg", "-hide_banner", "-filters"]).stdout
    missing = [name for name in (*ENCODERS, "silencedetect") if name not in encoders + filters]
    return report(not missing, "ffmpeg with " + ", ".join((*ENCODERS, "silencedetect")),
                  f"this ffmpeg lacks {', '.join(missing)}: {FFMPEG_HELP}")


def check_pillow() -> None:
    try:
        import PIL  # noqa: F401
        print("[ok] Pillow (optional, for frames.py)")
    except ImportError:
        print("[--] Pillow not installed (optional, only for frames.py): pip install pillow")


def check_ytdlp() -> None:
    command = ytdlp_command()
    if command is None:
        print(f"[--] yt-dlp not installed (optional, for links to TikTok, Vimeo, Instagram, X...): {YTDLP_HELP}")
        return
    print(f"[ok] yt-dlp {run([*command, '--version']).stdout.strip()} (optional, for links to video sites)")


def check_key() -> str | None:
    key = os.environ.get(KEY_ENV, "").strip()
    if key:
        report(True, f"{KEY_ENV} is set")
        return key
    note = f" ({GENERIC_KEY_ENV} is set but this skill does not read it)" if os.environ.get(GENERIC_KEY_ENV) else ""
    report(False, f"{KEY_ENV} is not set{note}",
           f"set it in your shell profile (export {KEY_ENV}='...') or system environment, then restart the agent")
    return None


def check_account(key: str) -> bool:
    try:
        data = get_json("key", key).get("data", {})
    except SystemExit as exc:
        return report(False, "OpenRouter key accepted", str(exc).removeprefix("error: "))
    remaining = data.get("limit_remaining")
    detail = f", credit left: ${remaining:.2f}" if isinstance(remaining, (int, float)) else ""
    return report(True, f"OpenRouter key accepted (usage so far: ${data.get('usage', 0):.2f}{detail})")


def check_model(key: str, model: str) -> bool:
    try:
        models = get_json("models", key).get("data", [])
    except SystemExit as exc:
        return report(False, f"model {model}", str(exc).removeprefix("error: "))
    entry = next((m for m in models if m.get("id") == model), None)
    if entry is None:
        return report(False, f"model {model} is available", "pick another with --model or $MUS_MODEL")
    inputs = set(entry.get("architecture", {}).get("input_modalities", []))
    missing = {"image", "audio", "video"} - inputs
    return report(not missing, f"model {model} takes image, audio and video",
                  f"it lacks {', '.join(sorted(missing))}: pick another with --model or $MUS_MODEL")


def live_test() -> bool:
    with scratch_dir("media_doctor_") as workdir:
        image = workdir / "red.png"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64",
             "-frames:v", "1", str(image)])
        script = Path(__file__).with_name("ask.py")
        result = subprocess.run([sys.executable, "-B", str(script), str(image), "-q", "One word: the color?"],
                                capture_output=True, text=True)
    answer = result.stdout.strip()
    return report(result.returncode == 0 and "red" in answer.lower(), f"live request answered: {answer or result.stderr.strip()[:120]}",
                  "see the error above")


def main() -> None:
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="also send one tiny test request (about $0.001)")
    args = parser.parse_args()

    results = [check_python(), check_ffmpeg()]
    check_pillow()
    check_ytdlp()
    key = check_key()
    results.append(key is not None)
    if key:
        results += [check_account(key), check_model(key, DEFAULT_MODEL)]
        if args.live and all(results):
            results.append(live_test())
    print("\nAll good." if all(results) else "\nSome checks failed: fix them and run doctor.py again.")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
