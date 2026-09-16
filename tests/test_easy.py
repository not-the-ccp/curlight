import gc
import json

import pytest

from curlight import Curl, CurlInfo, CurlOpt, Headers, Response, version


def test_native_types_and_lifetimes(base_url):
    chunks = []
    with Curl() as curl:
        curl.setopt(CurlOpt.URL, base_url)
        curl.setopt(CurlOpt.HTTPHEADER, ["X-Test: hello"])
        curl.setopt(CurlOpt.POSTFIELDS, b"a\0b")
        curl.setopt(CurlOpt.WRITEFUNCTION, chunks.append)
        curl.setopt(CurlOpt.TIMEOUT_MS, 5000)
        gc.collect()
        curl.perform()
        assert curl.getinfo(CurlInfo.RESPONSE_CODE) == 200
        assert curl.getinfo(CurlInfo.SIZE_DOWNLOAD_T) == len(b"".join(chunks))
        assert curl.getinfo(CurlInfo.TOTAL_TIME) >= 0
        echo = json.loads(b"".join(chunks))
        assert echo["body"] == "a\0b"
        assert echo["headers"]["X-Test"] == "hello"
        curl.setopt(CurlOpt.HTTPHEADER, None)
        curl.reset()
    curl.close()
    with pytest.raises(RuntimeError):
        curl.perform()


def test_safe_marshalling(base_url):
    with Curl() as curl:
        with pytest.raises(NotImplementedError):
            curl.setopt(CurlOpt.WRITEDATA, 12345)
        with pytest.raises(NotImplementedError):
            curl.setopt(CurlOpt.DEBUGFUNCTION, lambda *args: None)
        with pytest.raises(NotImplementedError):
            curl.getinfo(CurlInfo.CERTINFO)
        with pytest.raises(TypeError):
            curl.setopt(CurlOpt.TIMEOUT, "1")
        with pytest.raises(TypeError):
            curl.setopt(CurlOpt.HTTPHEADER, "X-Test: x")
        with pytest.raises(ValueError):
            curl.setopt(CurlOpt.URL, base_url + "\0x")
        with pytest.raises(ValueError):
            curl.setopt(CurlOpt.HTTPHEADER, ["a\0b"])
        with pytest.raises(ValueError):
            curl.setopt(CurlOpt.ERRORBUFFER, b"x")
        curl.setopt(CurlOpt.CAINFO_BLOB, b"test certificate bytes")


def test_read_and_progress_callbacks(base_url):
    counts, chunks = [], []
    with Curl() as curl:
        curl.setopt(CurlOpt.URL, base_url)
        curl.setopt(CurlOpt.UPLOAD, 1)
        curl.setopt(CurlOpt.INFILESIZE_LARGE, 3)
        curl.setopt(CurlOpt.READFUNCTION, lambda size: b"abc")
        curl.setopt(CurlOpt.XFERINFOFUNCTION, lambda *args: counts.append(args))
        curl.setopt(CurlOpt.NOPROGRESS, 0)
        curl.setopt(CurlOpt.WRITEFUNCTION, chunks.append)
        curl.perform()
        assert json.loads(b"".join(chunks))["body"] == "abc"
        assert counts


def test_callback_error_and_reentrancy(base_url):
    with Curl() as curl:
        curl.setopt(CurlOpt.URL, base_url)
        curl.setopt(CurlOpt.WRITEFUNCTION, lambda data: curl.close())
        with pytest.raises(RuntimeError, match="in use"):
            curl.perform()
        curl.setopt(CurlOpt.WRITEFUNCTION, lambda data: None)
        curl.perform()


def test_non_http_protocol(tmp_path):
    path = tmp_path / "data"
    path.write_bytes(b"local data")
    chunks = []
    with Curl() as curl:
        curl.setopt(CurlOpt.URL, path.as_uri())
        curl.setopt(CurlOpt.WRITEFUNCTION, chunks.append)
        curl.perform()
    assert b"".join(chunks) == b"local data"


def test_models():
    headers = Headers([("X-Test", "1"), ("x-test", "2"), ("Other", "3")])
    assert len(headers) == 2
    assert list(headers) == ["X-Test", "Other"]
    assert headers["X-TEST"] == "1, 2"
    assert headers.get_list("x-test") == ["1", "2"]
    assert headers.get("missing") is None
    response = Response(
        200, "http://local", Headers({"Content-Type": "text/plain; charset=latin-1"}), b"\xe9"
    )
    assert response.text == "é"
    assert (
        Response(200, "url", Headers({"Content-Type": "text/plain; charset=madeup"}), b"ok").text
        == "ok"
    )
    assert "libcurl/" in version()
