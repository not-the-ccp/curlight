# curlight

[![CI](https://github.com/not-the-ccp/curlight/actions/workflows/ci.yml/badge.svg)](https://github.com/not-the-ccp/curlight/actions/workflows/ci.yml)

Pythonic HTTP sessions over **real libcurl**. A small high-level API, a safe
low-level escape hatch, and native concurrent transfers—not subprocesses and not
an HTTP client reimplemented in Python.

**Status: 0.1.0 alpha.** Useful, tested foundations; not a drop-in PycURL replacement
or an exhaustive binding of every libcurl interface. See [coverage and limitations](docs/api.md#coverage-and-limitations).

## Install

Python **3.10+**, system libcurl **7.85.0+**. Linux and macOS are CI targets.
The package does not bundle libcurl or a CA store. It has **no required Python
dependencies** and requires no compiler or curl headers to install.

```sh
# Debian / Ubuntu (runtime package name varies by distribution)
sudo apt install libcurl4

# From this repository; not yet published to PyPI
python -m pip install .
# Optional preferred backend:
python -m pip install '.[cffi]'
```

CFFI is preferred when installed, with a stdlib `ctypes` fallback. Force either
with `CURLIGHT_BACKEND=cffi` or `CURLIGHT_BACKEND=ctypes` before import.
`CURLIGHT_LIBCURL=/absolute/path/to/libcurl.so` overrides library discovery.

## Familiar HTTP API

```python
import curlight

with curlight.Session(headers={"Accept": "application/json"}, timeout=10) as session:
    response = session.get("https://httpbin.org/get", params={"tag": ["a", "b"]})
    response.raise_for_status()
    print(response.json())

    response = session.post("https://httpbin.org/post", json={"hello": "world"})
    print(response.status_code, response.elapsed)
```

Top-level `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, and `request`
create short-lived sessions. Use a `Session` to reuse connections and cookies.
TLS certificate and hostname verification are on by default.

### Uploads and bounded downloads

```python
from curlight import Upload, get, post

with open("report.csv", "rb") as source:
    response = post(
        "https://httpbin.org/post",
        data={"description": "monthly report"},
        files={"report": Upload("report.csv", source, "text/csv")},
    )

with open("download.bin", "wb") as output:
    response = get("https://example.com/file", sink=output, max_bytes=100_000_000)
    response.raise_for_status()
```

Multipart uploads are buffered (64 MiB default encoded-body limit). Downloads
with `sink` deliver chunks without buffering the response body. The caller owns
file objects; failed downloads may leave partial output. Ordinary responses have
a 64 MiB default decoded-body limit. Set `max_bytes=None` to explicitly uncap it.

### Native async concurrency

```python
import asyncio
from curlight import AsyncSession

async def main():
    async with AsyncSession(max_connections=10, timeout=15) as session:
        responses = await asyncio.gather(
            session.get("https://example.com"),
            session.get("https://example.org"),
        )
        print([r.status_code for r in responses])

asyncio.run(main())
```

`AsyncSession` uses `curl_multi`, shares its connection cache and cookies, and
removes native handles on cancellation. It currently polls cooperatively every
10 ms; it does not use executor threads or socket callbacks. A libcurl build with
a synchronous DNS resolver can block the event loop during name resolution.

### Low-level libcurl

```python
from curlight import Curl, CurlInfo, CurlOpt

chunks = []
with Curl() as curl:
    curl.setopt(CurlOpt.URL, "https://example.com")
    curl.setopt(CurlOpt.TIMEOUT_MS, 10_000)
    curl.setopt(CurlOpt.WRITEFUNCTION, chunks.append)
    curl.perform()
    print(curl.getinfo(CurlInfo.RESPONSE_CODE))
```

Generated constants cover options and enums from libcurl 8.14.1. Scalar/string,
string-list, blob, body, read/write/header, and progress arguments are marshalled
and kept alive safely. Unsupported pointer types and callback signatures raise
`NotImplementedError`. Newer options can be rejected by older libcurl runtimes.
The low-level API also supports non-HTTP protocols provided by your libcurl build.

## Documentation

- [API, defaults, security and supported native interfaces](docs/api.md)
- [Runnable examples](examples/)
- [Contributing and local checks](CONTRIBUTING.md)
- [Security reporting](SECURITY.md)
- [Changelog](CHANGELOG.md)

MIT licensed. This project is independent of curl and PycURL.
