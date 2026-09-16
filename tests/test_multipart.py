import io
from email import policy
from email.parser import BytesParser

import pytest

from curlight import Upload, post


def test_multipart(base_url):
    stream = io.BytesIO(b"before-file\0content")
    stream.seek(7)
    response = post(
        base_url,
        data={"label": "hello"},
        files={
            "file": Upload('test"file.bin', stream),
            "other": Upload("note.txt", b"note", "text/plain"),
        },
    )
    echo = response.json()
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {echo['headers']['Content-Type']}\r\n\r\n".encode()
        + echo["body"].encode("latin-1")
    )
    parts = list(message.iter_parts())
    assert [p.get_payload(decode=True) for p in parts] == [b"hello", b"file\0content", b"note"]
    assert parts[1].get_filename() == 'test"file.bin'
    assert not stream.closed


def test_multipart_validation(base_url):
    with pytest.raises(ValueError, match="max_upload_bytes"):
        post(base_url, files={"f": Upload("x", io.BytesIO(b"x" * 10000))}, max_upload_bytes=500)
    with pytest.raises(ValueError):
        post(base_url, files={"f": Upload("x\r\nInjected: value", b"x")})
    with pytest.raises(ValueError):
        post(base_url, files={}, json={})
    with pytest.raises(ValueError):
        post(base_url, files={}, headers={"Content-Type": "incorrect"})
    with pytest.raises(TypeError):
        post(base_url, files={"f": Upload("x", io.StringIO("text"))})
