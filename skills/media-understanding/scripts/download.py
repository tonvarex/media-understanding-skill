"""Inputs given as links: direct file downloads, and pages of video sites (YouTube, TikTok, ...) through yt-dlp."""
from __future__ import annotations

import importlib.util
import mimetypes
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from util import fail, log

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
PAGE_TYPES = {"text/html", "application/xhtml+xml"}
BLOCKED_STATUSES = {401, 403, 429}
MAX_DOWNLOAD_BYTES = 1_000_000_000
CHUNK_BYTES = 1 << 20
VIDEO_FORMAT = "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b"
AUDIO_FORMAT = "ba/b"
YTDLP_HELP = "macOS `brew install yt-dlp`, Linux `pip install yt-dlp`, Windows `winget install yt-dlp`"


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def is_youtube(url: str) -> bool:
    return urllib.parse.urlparse(url).hostname in YOUTUBE_HOSTS


def ytdlp_command() -> list[str] | None:
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    return None


def download_with_ytdlp(url: str, directory: Path, audio_only: bool) -> Path:
    command = ytdlp_command()
    if command is None:
        fail(f"{url} is a page of a video site and needs yt-dlp, install it: {YTDLP_HELP}")
    log(f"Downloading {url} with yt-dlp (long videos take a few minutes) ...")
    directory.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [*command, "--no-playlist", "--no-warnings", "--quiet", "--no-simulate", "--max-filesize", "1G",
         "-f", AUDIO_FORMAT if audio_only else VIDEO_FORMAT,
         "-o", str(directory / "%(id)s.%(ext)s"), "--print", "after_move:filepath", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = result.stdout.strip().splitlines()
    path = Path(lines[-1]) if lines else None
    if result.returncode or path is None or not path.is_file():
        reason = (result.stderr.strip().splitlines() or ["nothing was downloaded (over 1 GB?)"])[-1]
        fail(f"yt-dlp could not download {url}: {reason.removeprefix('ERROR: ')}")
    return path


def _filename(url: str, response) -> str:
    disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disposition)
    name = urllib.parse.unquote(match.group(1) if match else Path(urllib.parse.urlparse(url).path).name)
    name = re.sub(r"[^\w.\- ]", "_", name)[:120] or "download"
    if not Path(name).suffix:
        extension = mimetypes.guess_extension(response.headers.get_content_type() or "")
        name += extension or ".bin"
    return name


def download(url: str, directory: Path, audio_only: bool = False) -> Path:
    if is_youtube(url):
        return download_with_ytdlp(url, directory / "ytdlp", audio_only)
    log(f"Downloading {url} ...")
    request = urllib.request.Request(url, headers={"User-Agent": "media-understanding/1.1"})
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.headers.get_content_type() in PAGE_TYPES:
                return download_with_ytdlp(url, directory / "ytdlp", audio_only)
            destination = directory / _filename(url, response)
            size = 0
            with destination.open("wb") as file:
                while chunk := response.read(CHUNK_BYTES):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        fail(f"{url} is larger than {MAX_DOWNLOAD_BYTES // 1_000_000} MB")
                    file.write(chunk)
    except urllib.error.HTTPError as exc:
        if exc.code in BLOCKED_STATUSES and ytdlp_command():
            return download_with_ytdlp(url, directory / "ytdlp", audio_only)
        fail(f"cannot download {url}: HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError) as exc:
        fail(f"cannot download {url}: {exc}")
    return destination


def local_input(value: str, directory: Path, audio_only: bool = False) -> Path:
    if is_url(value):
        return download(value, directory / "downloads", audio_only)
    path = Path(value).expanduser()
    if not path.is_file():
        fail(f"no such file: {value}")
    return path
