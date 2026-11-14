"""Inputs given as links: plain downloads, plus detection of YouTube links."""
from __future__ import annotations

import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from util import fail, log

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
MAX_DOWNLOAD_BYTES = 1_000_000_000
CHUNK_BYTES = 1 << 20


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def is_youtube(url: str) -> bool:
    return urllib.parse.urlparse(url).hostname in YOUTUBE_HOSTS


def _filename(url: str, response) -> str:
    disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disposition)
    name = urllib.parse.unquote(match.group(1) if match else Path(urllib.parse.urlparse(url).path).name)
    name = re.sub(r"[^\w.\- ]", "_", name)[:120] or "download"
    if not Path(name).suffix:
        extension = mimetypes.guess_extension(response.headers.get_content_type() or "")
        name += extension or ".bin"
    return name


def download(url: str, directory: Path) -> Path:
    log(f"Downloading {url} ...")
    request = urllib.request.Request(url, headers={"User-Agent": "media-understanding/1.0"})
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            destination = directory / _filename(url, response)
            size = 0
            with destination.open("wb") as file:
                while chunk := response.read(CHUNK_BYTES):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        fail(f"{url} is larger than {MAX_DOWNLOAD_BYTES // 1_000_000} MB")
                    file.write(chunk)
    except urllib.error.HTTPError as exc:
        fail(f"cannot download {url}: HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError) as exc:
        fail(f"cannot download {url}: {exc}")
    return destination


def local_input(value: str, directory: Path) -> Path:
    if is_url(value):
        return download(value, directory / "downloads")
    path = Path(value).expanduser()
    if not path.is_file():
        fail(f"no such file: {value}")
    return path
