"""Pythonic synchronous HTTP client built on a reusable libcurl easy handle."""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from ._easy import Curl
from .constants import CurlInfo, CurlOpt
from .models import Headers, Response


class Session:
    """Reusable connections and cookies. Not safe for concurrent use."""

    def __init__(self, *, headers: Mapping[str, str] | None = None,
                 timeout: float | None = 30, verify: bool | str = True) -> None:
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.verify = verify
        self._curl = Curl()
        self._closed = False

    def request(self, method: str, url: str, *, timeout: float | None = 30) -> Response:
        if self._closed:
            raise RuntimeError("Session is closed")
        if urlsplit(url).scheme.lower() not in {"http", "https"}:
            raise ValueError("Session supports only http:// and https:// URLs; use Curl otherwise")
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", method):
            raise ValueError("invalid HTTP method")
        curl = self._curl
        curl.reset()
        curl.setopt(CurlOpt.URL, url)
        curl.setopt(CurlOpt.CUSTOMREQUEST, method.upper())
        curl.setopt(CurlOpt.PROTOCOLS_STR, "http,https")
        curl.setopt(CurlOpt.REDIR_PROTOCOLS_STR, "http,https")
        curl.setopt(CurlOpt.FOLLOWLOCATION, 1)
        curl.setopt(CurlOpt.MAXREDIRS, 10)
        curl.setopt(CurlOpt.COOKIEFILE, "")
        if timeout is not None:
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("timeout must be positive and finite, or None")
            curl.setopt(CurlOpt.TIMEOUT_MS, max(1, math.ceil(timeout * 1000)))
        chunks: list[bytes] = []
        raw: list[bytes] = []
        curl.setopt(CurlOpt.WRITEFUNCTION, chunks.append)
        curl.setopt(CurlOpt.HEADERFUNCTION, raw.append)
        curl.perform()
        pairs = []
        reason = ""
        for line in b"".join(raw).splitlines():
            if line.startswith(b"HTTP/"):
                pairs = []
                parts = line.decode("latin-1").split(" ", 2)
                reason = parts[2] if len(parts) > 2 else ""
            elif b":" in line:
                name, value = line.split(b":", 1)
                pairs.append((name.decode("latin-1"), value.strip().decode("latin-1")))
        return Response(curl.getinfo(CurlInfo.RESPONSE_CODE),
                        curl.getinfo(CurlInfo.EFFECTIVE_URL), Headers(pairs),
                        b"".join(chunks), reason, curl.getinfo(CurlInfo.TOTAL_TIME))

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def close(self) -> None:
        self._curl.close()
        self._closed = True

    def __enter__(self) -> Session:
        if self._closed:
            raise RuntimeError("Session is closed")
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def request(method: str, url: str, **kwargs: Any) -> Response:
    with Session() as session:
        return session.request(method, url, **kwargs)


def get(url: str, **kwargs: Any) -> Response:
    return request("GET", url, **kwargs)
