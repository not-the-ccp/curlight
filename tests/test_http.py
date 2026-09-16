import base64
import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

import curlight as c


@pytest.mark.parametrize("verb", ["get", "post", "put", "patch", "delete", "options"])
def test_verbs(base_url, verb):
    response = getattr(c, verb)(base_url)
    assert response.json()["method"] == verb.upper()
    assert response.ok
    assert response.raise_for_status() is response
    assert response.elapsed >= 0


def test_head(base_url):
    assert c.head(base_url).content == b""


def test_bodies_and_params(base_url):
    response = c.post(base_url + "?original=yes", params={"a": [1, 2]}, json={"snow": "☃"})
    echo = response.json()
    assert json.loads(echo["body"]) == {"snow": "☃"}
    assert echo["headers"]["Content-Type"] == "application/json"
    assert parse_qs(urlsplit(echo["path"]).query) == {"original": ["yes"], "a": ["1", "2"]}
    assert c.post(base_url, data=b"a\0b").json()["body"] == "a\0b"
    assert c.post(base_url, json=None).json()["body"] == "null"
    echo = c.post(base_url, data={"a": [1, 2]}).json()
    assert echo["body"] == "a=1&a=2"
    assert echo["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    with pytest.raises(ValueError):
        c.post(base_url, data="x", json={})


def test_session_state(base_url):
    with c.Session(headers={"X-Test": "default"}) as session:
        first = session.post(base_url, data="a").json()
        second = session.get(base_url, headers={"x-test": "override"}).json()
        assert second["method"] == "GET" and second["body"] == ""
        assert first["port"] == second["port"]  # actual TCP connection reuse
        assert second["headers"]["x-test"] == "override"
        response = session.get(base_url + "/cookies")
        assert response.headers.get_list("set-cookie") == ["one=1; Path=/", "two=2; Path=/"]
        assert len(session.cookies) == 2
        assert "one=1" in session.get(base_url).json()["headers"]["Cookie"]
        session.clear_cookies()
        assert session.cookies == ()
        assert "Cookie" not in session.get(base_url).json()["headers"]
    session.close()
    with pytest.raises(RuntimeError):
        session.get(base_url)


@pytest.mark.parametrize(
    "status,method", [(301, "GET"), (302, "GET"), (303, "GET"), (307, "POST"), (308, "POST")]
)
def test_redirects(base_url, status, method):
    response = c.post(base_url + "/redirect", params={"status": status}, data="payload")
    assert len(response.history) == 1
    assert response.history[0].status_code == status
    assert response.json()["method"] == method
    assert response.json()["body"] == ("payload" if method == "POST" else "")
    assert response.url == base_url + "/echo"


def test_redirect_limits_and_restrictions(base_url):
    response = c.get(base_url + "/redirect", allow_redirects=False)
    assert response.status_code == 302 and response.content == b"redirect body"
    with pytest.raises(c.TooManyRedirects):
        c.get(base_url + "/redirect", max_redirects=0)
    with pytest.raises(ValueError):
        c.get(base_url + "/redirect", params={"to": "file:///etc/passwd"})


def test_no_credentials_across_origins(base_url, server_factory):
    other = server_factory()
    response = c.get(
        base_url + "/redirect",
        params={"to": other},
        headers={"Authorization": "secret", "Cookie": "secret=1"},
        auth=("a", "b"),
    )
    assert "Authorization" not in response.json()["headers"]
    assert "Cookie" not in response.json()["headers"]


def test_auth(base_url):
    with c.Session(auth=("name", "password")) as session:
        auth = session.get(base_url).json()["headers"]["Authorization"]
        assert auth == "Basic " + base64.b64encode(b"name:password").decode()


def test_compression_streaming_limits(base_url):
    assert c.get(base_url + "/gzip").text == "compressed response"
    output = io.BytesIO()
    response = c.get(base_url + "/large", sink=output)
    assert response.content == b""
    assert output.getvalue() == b"x" * 100000
    with pytest.raises(ValueError, match="max_bytes"):
        c.get(base_url + "/large", max_bytes=100)
    with pytest.raises(OSError, match="short write"):
        c.get(base_url, sink=lambda data: 0)
    output = io.BytesIO()
    c.get(base_url + "/redirect", params={"to": "/large"}, sink=output)
    assert output.getvalue() == b"x" * 100000


def test_http_error(base_url):
    response = c.get(base_url + "/status?code=418")
    assert not response.ok
    with pytest.raises(c.HTTPError) as error:
        response.raise_for_status()
    assert error.value.response is response


def test_timeouts_and_recovery(base_url):
    with c.Session(timeout=0.02) as session:
        with pytest.raises(c.Timeout) as error:
            session.get(base_url + "/delay")
        assert error.value.code == 28
        assert session.get(base_url, timeout=5).ok
    for timeout in [0, -1, float("inf"), float("nan"), True]:
        with pytest.raises(ValueError):
            c.get(base_url, timeout=timeout)
    assert c.get(base_url, timeout=None).ok


def test_tls(tls_url, tls_cert):
    with pytest.raises(c.SSLError):
        c.get(tls_url)
    assert c.get(tls_url, verify=str(tls_cert[0])).ok
    assert c.get(tls_url, verify=False).ok


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/x",
        "ftp://localhost",
        "http://a\nX: y",
        "http://u:p@localhost",
        "http://localhost:99999",
        "relative",
    ],
)
def test_url_validation(url):
    with pytest.raises(ValueError):
        c.get(url)


@pytest.mark.parametrize(
    "headers",
    [
        {"X": "a\r\nb"},
        {"Bad Name": "x"},
        {"X": "\0"},
        {"Content-Length": "0"},
        {"Transfer-Encoding": "chunked"},
    ],
)
def test_header_validation(base_url, headers):
    with pytest.raises(ValueError):
        c.get(base_url, headers=headers)


def test_reentrant_session(base_url):
    with c.Session() as session:
        with pytest.raises(RuntimeError, match="concurrently"):
            session.get(base_url, sink=lambda data: session.get(base_url))
        assert session.get(base_url).ok
