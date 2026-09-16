"""Public exception hierarchy."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Response


class CurlError(Exception):
    """A libcurl failure; ``code`` preserves the native result code."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


class Timeout(CurlError):
    """The transfer or connection timed out."""


class ConnectionError(CurlError):
    """DNS resolution or connection establishment failed."""


class SSLError(CurlError):
    """TLS negotiation or certificate verification failed."""


class TooManyRedirects(CurlError):
    """The configured redirect limit was exceeded."""


class HTTPError(Exception):
    """An HTTP error raised explicitly by Response.raise_for_status()."""

    def __init__(self, response: Response) -> None:
        self.response = response
        super().__init__(f"HTTP {response.status_code} {response.reason} for {response.url}")


def error_for(code: int, message: str) -> CurlError:
    cls = {
        5: ConnectionError,
        6: ConnectionError,
        7: ConnectionError,
        28: Timeout,
        35: SSLError,
        47: TooManyRedirects,
        58: SSLError,
        60: SSLError,
        77: SSLError,
        90: SSLError,
    }.get(code, CurlError)
    return cls(code, message)
