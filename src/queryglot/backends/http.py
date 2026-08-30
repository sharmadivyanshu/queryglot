"""Tiny HTTP helper with an injectable transport, so every backend is fully
testable without a server and honestly integration-tested with one."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

# transport(method, url, body, headers) -> (status_code, response_text)
Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, str]]


def urllib_transport(
    method: str, url: str, body: bytes | None, headers: dict[str, str]
) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def get_json(transport: Transport, url: str) -> dict:
    status, text = transport("GET", url, None, {})
    if status >= 400:
        raise ConnectionError(f"GET {url} -> {status}: {text[:200]}")
    return json.loads(text)


def post_form(transport: Transport, url: str, fields: dict[str, str]) -> tuple[int, dict]:
    body = urllib.parse.urlencode(fields).encode()
    status, text = transport(
        "POST", url, body, {"Content-Type": "application/x-www-form-urlencoded"}
    )
    return status, json.loads(text)


def post_json(transport: Transport, url: str, payload: dict) -> tuple[int, dict]:
    status, text = transport(
        "POST", url, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    return status, json.loads(text)
