"""Small helpers shared by every script."""
from __future__ import annotations

import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn


@contextmanager
def scratch_dir(prefix: str) -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def fail(message: str) -> NoReturn:
    sys.exit(f"error: {message}")


def require_tools(*names: str) -> None:
    missing = [name for name in names if not shutil.which(name)]
    if missing:
        fail(f"{', '.join(missing)} not found on PATH "
             "(install ffmpeg: brew install ffmpeg | apt install ffmpeg | winget install ffmpeg)")


def clock(seconds: float, decimals: int = 0) -> str:
    total = round(seconds, decimals)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    width = decimals + 3 if decimals else 2
    stamp = f"{int(minutes):02d}:{secs:0{width}.{decimals}f}"
    return f"{int(hours)}:{stamp}" if hours else stamp
