"""Buffered multipart form encoding with explicit filenames and media types."""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import BinaryIO


@dataclass(frozen=True)
class Upload:
    """A multipart file. Caller retains ownership of file objects.

    Files are read from their current position and buffered up to the request's
    ``max_upload_bytes`` limit. Use Curl's read callback for unbuffered uploads.
    """

    filename: str
    content: bytes | BinaryIO
    content_type: str = "application/octet-stream"


def _quote(value: str) -> str:
    if any(c in value for c in "\r\n\0"):
        raise ValueError("invalid multipart field name or filename")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def encode_multipart(
    data: Mapping[str, object] | Iterable[tuple[str, object]] | None,
    files: Mapping[str, Upload] | Iterable[tuple[str, Upload]],
    limit: int,
) -> tuple[bytes, str]:
    if limit < 0:
        raise ValueError("max_upload_bytes must be nonnegative")
    boundary = "curlight-" + secrets.token_hex(24)
    chunks: list[bytes] = []
    total = 0

    def add(chunk: bytes) -> None:
        nonlocal total
        total += len(chunk)
        if total > limit:
            raise ValueError(f"multipart body exceeded max_upload_bytes={limit}")
        chunks.append(chunk)

    def disposition(name: str, filename: str | None = None) -> bytes:
        text = f'--{boundary}\r\nContent-Disposition: form-data; name="{_quote(name)}"'
        if filename is not None:
            text += f'; filename="{_quote(filename)}"'
        return (text + "\r\n").encode()

    for name, value in data.items() if isinstance(data, Mapping) else data or ():
        add(disposition(name) + b"\r\n")
        add(value if isinstance(value, bytes) else str(value).encode())
        add(b"\r\n")
    for name, upload in files.items() if isinstance(files, Mapping) else files:
        if not isinstance(upload, Upload):
            raise TypeError("files values must be Upload instances")
        if any(c in upload.content_type for c in "\r\n\0"):
            raise ValueError("invalid multipart content type")
        add(disposition(name, upload.filename))
        add(f"Content-Type: {upload.content_type}\r\n\r\n".encode())
        if isinstance(upload.content, bytes):
            add(upload.content)
        else:
            while True:
                chunk = upload.content.read(min(65536, limit - total + 1))
                if not isinstance(chunk, bytes):
                    raise TypeError("Upload streams must be binary")
                if not chunk:
                    break
                add(chunk)
        add(b"\r\n")
    add(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
