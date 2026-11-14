"""Minimal OpenRouter client: API key lookup, JSON requests with retries and readable errors."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from util import fail

API_URL = "https://openrouter.ai/api/v1"
KEY_ENV = "MUS_OPENROUTER_API_KEY"
GENERIC_KEY_ENV = "OPENROUTER_API_KEY"
RETRY_DELAY_SECONDS = 3
RETRYABLE_CODES = {408, 429}

HINTS = {
    401: "the API key is invalid or revoked",
    402: "the OpenRouter account has no credit left",
    403: "the request was blocked (moderation or region)",
    404: "model not found: check --model",
    413: "request too large: lower --max-mb or --height",
    429: "rate limited: lower --parallel or retry later",
}


def api_key() -> str:
    key = os.environ.get(KEY_ENV, "").strip()
    if key:
        return key
    generic = (f" {GENERIC_KEY_ENV} is set but is not used: set {KEY_ENV} to the same value to use it."
               if os.environ.get(GENERIC_KEY_ENV) else "")
    fail(f"{KEY_ENV} is not set.{generic} Set it in your shell profile or system environment, "
         "restart the agent, and run doctor.py to check (see the README, 'Setup')")


def describe_error(code: int, detail: object) -> str:
    message = detail.get("message") if isinstance(detail, dict) else str(detail)
    hint = f" ({HINTS[code]})" if code in HINTS else ""
    return f"HTTP {code}: {str(message)[:300]}{hint}"


def is_retryable(code: int) -> bool:
    return code in RETRYABLE_CODES or code >= 500


def request_json(method: str, endpoint: str, key: str, payload: dict | None = None,
                 timeout: int = 900, retries: int = 2) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    error = ""
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(RETRY_DELAY_SECONDS * attempt)
        request = urllib.request.Request(f"{API_URL}/{endpoint}", data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(raw)["error"]
            except (ValueError, KeyError, TypeError):
                detail = raw
            error = describe_error(exc.code, detail)
            if not is_retryable(exc.code):
                break
            continue
        except (urllib.error.URLError, TimeoutError) as exc:
            error = f"network error: {exc}"
            continue
        if isinstance(data, dict) and data.get("error"):
            code = int(data["error"].get("code") or 502) if isinstance(data["error"], dict) else 502
            error = describe_error(code, data["error"])
            if not is_retryable(code):
                break
            continue
        return data
    fail(f"OpenRouter {endpoint}: {error}")


def post_json(endpoint: str, payload: dict, key: str, timeout: int = 900) -> dict:
    return request_json("POST", endpoint, key, payload, timeout)


def get_json(endpoint: str, key: str) -> dict:
    return request_json("GET", endpoint, key, timeout=30, retries=1)
