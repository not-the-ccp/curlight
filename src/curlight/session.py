"""Pythonic synchronous HTTP client built on reusable libcurl easy handles."""

from __future__ import annotations

import json as json_module
import math
import re
from collections.abc import Callable, Generator, Iterable, Mapping
from typing import Any, BinaryIO
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from ._easy import Curl
from .constants import CurlAuth, CurlInfo, CurlOpt
from .exceptions import TooManyRedirects
from .models import Headers, Response
from .multipart import Upload, encode_multipart

_UNSET = object()
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
HeaderInput = Mapping[str, str] | Iterable[tuple[str, str]]


def _headers(values: HeaderInput) -> dict[str, tuple[str, str]]:
    result = {}
    for name, value in values.items() if isinstance(values, Mapping) else values:
        if not isinstance(name, str) or not _TOKEN.fullmatch(name):
            raise ValueError("invalid HTTP header name")
        if not isinstance(value, str) or any(c in value for c in "\r\n\0"):
            raise ValueError("invalid HTTP header value")
        # libcurl's HTTP header interface takes bytes; HTTP field values are Latin-1.
        value.encode("latin-1")
        result[name.lower()] = (name, value)
    return result


def _url(url: str) -> str:
    if not isinstance(url, str) or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise ValueError("URL must be a string without whitespace or control characters")
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("Session requires an absolute http(s) URL; use Curl for other protocols")
    if parts.username is not None or parts.password is not None:
        raise ValueError("use auth=(username, password), not credentials embedded in a URL")
    _ = parts.port  # Validate malformed/out-of-range ports before calling libcurl.
    return urlunsplit(parts._replace(fragment=""))


def _origin(url: str) -> tuple[str, str | None, int]:
    p = urlsplit(url)
    return p.scheme, p.hostname, p.port or (443 if p.scheme == "https" else 80)


def _milliseconds(value: float | None) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError("timeout must be positive and finite, or None")
    return max(1, math.ceil(value * 1000))


class _Collector:
    def __init__(
        self,
        url: str,
        sink: BinaryIO | Callable[[bytes], Any] | None,
        max_bytes: int | None,
        follow: bool,
    ) -> None:
        self.url, self.sink, self.max_bytes, self.follow = url, sink, max_bytes, follow
        self.status = 0
        self.reason = ""
        self.pairs: list[tuple[str, str]] = []
        self.chunks: list[bytes] = []
        self.size = 0

    def header(self, line: bytes) -> None:
        if line.startswith(b"HTTP/"):
            parts = line.decode("latin-1").strip().split(" ", 2)
            self.status = int(parts[1])
            self.reason = parts[2] if len(parts) > 2 else ""
            self.pairs.clear()
        elif b":" in line:
            name, value = line.split(b":", 1)
            self.pairs.append((name.decode("latin-1"), value.strip().decode("latin-1")))

    def write(self, data: bytes) -> None:
        self.size += len(data)
        if self.max_bytes is not None and self.size > self.max_bytes:
            raise ValueError(f"response exceeded max_bytes={self.max_bytes}")
        if (
            self.follow
            and self.status in {301, 302, 303, 307, 308}
            and any(k.lower() == "location" for k, _ in self.pairs)
        ):
            return
        if self.sink is None:
            self.chunks.append(data)
        else:
            result = self.sink(data) if callable(self.sink) else self.sink.write(data)
            if result is not None and result != len(data):
                raise OSError("download sink performed a short write")

    def response(self, curl: Curl) -> Response:
        return Response(
            curl.getinfo(CurlInfo.RESPONSE_CODE),
            curl.getinfo(CurlInfo.EFFECTIVE_URL),
            Headers(self.pairs),
            b"".join(self.chunks),
            self.reason,
            curl.getinfo(CurlInfo.TOTAL_TIME),
        )


class Session:
    """Reusable connections and an in-memory libcurl cookie jar.

    Not thread-safe. Close deterministically with ``with Session() as session``.
    Timeouts are per redirect hop. Downloads stream synchronously to ``sink``;
    ordinary responses are buffered, subject to ``max_bytes``.
    """

    def __init__(
        self,
        *,
        headers: HeaderInput = (),
        timeout: float | None = 30,
        verify: bool | str = True,
        proxy: str | None = None,
        auth: tuple[str, str] | None = None,
    ) -> None:
        self.headers = Headers(headers)
        _headers(self.headers.multi_items())
        _milliseconds(timeout)
        self.timeout, self.verify, self.proxy, self.auth = timeout, verify, proxy, auth
        self._curl = Curl()
        self._closed = False
        self._busy = False

    def _request_steps(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        headers: HeaderInput = (),
        data: Any = None,
        json: Any = _UNSET,
        timeout: Any = _UNSET,
        files: Mapping[str, Upload] | Iterable[tuple[str, Upload]] | None = None,
        max_upload_bytes: int = 64 * 1024 * 1024,
        connect_timeout: float | None = 10,
        verify: Any = _UNSET,
        proxy: Any = _UNSET,
        auth: Any = _UNSET,
        cert: str | tuple[str, str] | None = None,
        allow_redirects: bool = True,
        max_redirects: int = 10,
        max_bytes: int | None = 64 * 1024 * 1024,
        sink: BinaryIO | Callable[[bytes], Any] | None = None,
    ) -> Generator[Curl, None, Response]:
        if self._closed:
            raise RuntimeError("Session is closed")
        if self._busy:
            raise RuntimeError("Session cannot be used concurrently")
        self._busy = True
        try:
            url = _url(url)
            if not isinstance(method, str) or not _TOKEN.fullmatch(method):
                raise ValueError("invalid HTTP method")
            method = method.upper()
            if max_redirects < 0 or (max_bytes is not None and max_bytes < 0):
                raise ValueError("max_redirects and max_bytes must be nonnegative")
            if params is not None:
                parts = urlsplit(url)
                query = urlencode(params, doseq=True)
                url = urlunsplit(parts._replace(query="&".join(filter(None, [parts.query, query]))))
            fields = _headers(self.headers.multi_items())
            fields.update(_headers(headers))
            body: bytes | None = None
            if files is not None:
                if json is not _UNSET:
                    raise ValueError("files and json are mutually exclusive")
                body, content_type = encode_multipart(data, files, max_upload_bytes)
                if "content-type" in fields:
                    raise ValueError("multipart Content-Type is managed by curlight")
                fields["content-type"] = ("Content-Type", content_type)
            elif json is not _UNSET:
                if data is not None:
                    raise ValueError("data and json are mutually exclusive")
                body = json_module.dumps(json, allow_nan=False, separators=(",", ":")).encode()
                fields.setdefault("content-type", ("Content-Type", "application/json"))
            elif data is not None:
                if isinstance(data, (bytes, bytearray, memoryview)):
                    body = bytes(data)
                elif isinstance(data, str):
                    body = data.encode()
                else:
                    body = urlencode(data, doseq=True).encode()
                    fields.setdefault(
                        "content-type", ("Content-Type", "application/x-www-form-urlencoded")
                    )
            if "content-length" in fields or "transfer-encoding" in fields:
                raise ValueError("request framing headers are managed by libcurl")
            timeout = self.timeout if timeout is _UNSET else timeout
            verify = self.verify if verify is _UNSET else verify
            proxy = self.proxy if proxy is _UNSET else proxy
            auth = self.auth if auth is _UNSET else auth
            if not isinstance(verify, (bool, str)) or verify == "":
                raise TypeError("verify must be a bool or a CA bundle path")
            history: list[Response] = []
            curl = self._curl
            while True:
                curl.reset()
                self._configure_shared_state(curl)
                curl.setopt(CurlOpt.URL, url)
                curl.setopt(CurlOpt.PROTOCOLS_STR, "http,https")
                curl.setopt(CurlOpt.REDIR_PROTOCOLS_STR, "http,https")
                curl.setopt(CurlOpt.FOLLOWLOCATION, 0)
                curl.setopt(CurlOpt.COOKIEFILE, "")
                curl.setopt(CurlOpt.ACCEPT_ENCODING, "")
                curl.setopt(CurlOpt.USERAGENT, "curlight/0.1.0")
                curl.setopt(CurlOpt.TIMEOUT_MS, _milliseconds(timeout))
                curl.setopt(CurlOpt.CONNECTTIMEOUT_MS, _milliseconds(connect_timeout))
                curl.setopt(CurlOpt.SSL_VERIFYPEER, int(verify is not False))
                curl.setopt(CurlOpt.SSL_VERIFYHOST, 0 if verify is False else 2)
                if isinstance(verify, str):
                    curl.setopt(CurlOpt.CAINFO, verify)
                if proxy is not None:
                    curl.setopt(CurlOpt.PROXY, proxy)
                if auth is not None:
                    username, password = auth
                    curl.setopt(CurlOpt.USERNAME, username)
                    curl.setopt(CurlOpt.PASSWORD, password)
                    curl.setopt(CurlOpt.HTTPAUTH, CurlAuth.BASIC)
                if cert is not None:
                    curl.setopt(CurlOpt.SSLCERT, cert if isinstance(cert, str) else cert[0])
                    if not isinstance(cert, str):
                        curl.setopt(CurlOpt.SSLKEY, cert[1])
                if body is not None:
                    curl.setopt(CurlOpt.POSTFIELDS, body)
                elif method == "POST":
                    curl.setopt(CurlOpt.POSTFIELDS, b"")
                if method == "HEAD":
                    curl.setopt(CurlOpt.NOBODY, 1)
                curl.setopt(CurlOpt.CUSTOMREQUEST, method)
                curl.setopt(
                    CurlOpt.HTTPHEADER,
                    [
                        (f"{name}: {value}" if value else f"{name};").encode("latin-1")
                        for name, value in fields.values()
                    ],
                )
                collector = _Collector(url, sink, max_bytes, allow_redirects)
                curl.setopt(CurlOpt.WRITEFUNCTION, collector.write)
                curl.setopt(CurlOpt.HEADERFUNCTION, collector.header)
                yield curl
                response = collector.response(curl)
                location = response.headers.get("location")
                if not (
                    allow_redirects
                    and location
                    and response.status_code in {301, 302, 303, 307, 308}
                ):
                    return Response(
                        response.status_code,
                        response.url,
                        response.headers,
                        response.content,
                        response.reason,
                        response.elapsed,
                        tuple(history),
                    )
                if len(history) >= max_redirects:
                    raise TooManyRedirects(47, f"exceeded {max_redirects} redirects")
                history.append(response)
                target = _url(urljoin(url, location))
                if _origin(target) != _origin(url):
                    # Never forward explicitly supplied credentials/cookies to another origin.
                    for name in ("authorization", "proxy-authorization", "cookie", "host"):
                        fields.pop(name, None)
                    auth = None
                if (response.status_code == 303 and method != "HEAD") or (
                    response.status_code in {301, 302} and method == "POST"
                ):
                    method, body = "GET", None
                    fields.pop("content-type", None)
                url = target
        finally:
            self._busy = False
            if not self._closed:
                self._curl.reset()

    def _configure_shared_state(self, curl: Curl) -> None:
        """Internal hook for AsyncSession's cookie share."""

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        steps = self._request_steps(method, url, **kwargs)
        try:
            while True:
                try:
                    curl = next(steps)
                except StopIteration as done:
                    return done.value
                curl.perform()
        finally:
            steps.close()

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Response:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> Response:
        kwargs.setdefault("allow_redirects", False)
        return self.request("HEAD", url, **kwargs)

    def options(self, url: str, **kwargs: Any) -> Response:
        return self.request("OPTIONS", url, **kwargs)

    @property
    def cookies(self) -> tuple[str, ...]:
        """Snapshot of libcurl's Netscape-format cookie records."""
        if self._busy:
            raise RuntimeError("Session is in use")
        return tuple(self._curl.getinfo(CurlInfo.COOKIELIST))

    def clear_cookies(self) -> None:
        if self._busy:
            raise RuntimeError("Session is in use")
        self._curl.setopt(CurlOpt.COOKIELIST, "ALL")

    def close(self) -> None:
        if self._busy:
            raise RuntimeError("Session is in use")
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


def post(url: str, **kwargs: Any) -> Response:
    return request("POST", url, **kwargs)


def put(url: str, **kwargs: Any) -> Response:
    return request("PUT", url, **kwargs)


def patch(url: str, **kwargs: Any) -> Response:
    return request("PATCH", url, **kwargs)


def delete(url: str, **kwargs: Any) -> Response:
    return request("DELETE", url, **kwargs)


def head(url: str, **kwargs: Any) -> Response:
    kwargs.setdefault("allow_redirects", False)
    return request("HEAD", url, **kwargs)


def options(url: str, **kwargs: Any) -> Response:
    return request("OPTIONS", url, **kwargs)
