# API reference and design notes

## HTTP requests

`request(method, url, **kwargs)` and verb helpers exist at module level and on
`Session`. `AsyncSession` exposes the same methods as coroutines.

Session construction:

```python
Session(headers=(), timeout=30, verify=True, proxy=None, auth=None)
AsyncSession(max_connections=20, **session_options)
```

Request options:

| Keyword | Meaning / default |
| --- | --- |
| `params` | Mapping or sequence of pairs, encoded with repeated values (`doseq=True`) |
| `headers` | Mapping or pairs; case-insensitive override of session headers |
| `data` | Bytes, string (UTF-8), or form mapping/pairs |
| `json` | JSON-serializable value, including `None`; exclusive with data/files |
| `files` | Mapping/pairs of field name to `Upload(filename, bytes_or_binary_file, content_type)` |
| `max_upload_bytes` | Maximum encoded multipart body, 64 MiB default |
| `timeout` | Total seconds **per hop**; inherits session default; `None` disables |
| `connect_timeout` | Connection phase seconds; default 10; `None` uses libcurl's default |
| `verify` | Inherits session setting: `True`, CA bundle path, or explicitly insecure `False` |
| `cert` | Client certificate path, or `(certificate_path, private_key_path)` |
| `proxy` | Inherits session setting; URL, `""` to disable, `None` for libcurl environment discovery |
| `auth` | Inherits session setting; `(username, password)` for Basic auth, or `None` |
| `allow_redirects` | True except HEAD helpers (False) |
| `max_redirects` | 10 |
| `max_bytes` | Maximum decoded bytes per hop, 64 MiB; `None` disables |
| `sink` | Binary writer or callable receiving bytes; `None` buffers into response |

A sink must return `None` or the number of bytes supplied. Callbacks run on the
calling thread / event loop, so slow sinks block progress. There is currently no
iterator-based streaming API or async sink. Body bytes from followed redirect
responses are discarded; final response bytes are streamed/buffered normally.

URL scheme restrictions apply to initial URLs and every redirect. 301/302 change
POST to GET; 303 changes non-HEAD requests to GET; 307/308 preserve method/body.
Cross-origin redirects remove explicit Authorization, Cookie, Proxy-Authorization,
and Host headers and disable request Basic auth for subsequent hops. Cookies
managed by libcurl continue to follow its domain/path/secure rules. Custom headers
with application-specific secrets are **not** automatically identified or removed.
Client certificate settings remain configured across redirects; disable redirects
when their destination must be pinned.

Header names/values reject control-character injection; request Content-Length and
Transfer-Encoding are managed by the client. Header values are Latin-1. URLs with
spaces/control characters or embedded credentials are rejected; percent-encode
paths and pass credentials via `auth` instead.

HTTP error statuses do not automatically raise. Network/timeout/callback errors do.
No automatic retries are performed (especially important for non-idempotent writes).

## Response and headers

`Response` is a frozen dataclass with:

- `status_code`, `url` (effective URL), `reason`
- `headers`: immutable case-insensitive `Headers`
- `content`: buffered bytes, empty when a sink was used
- `elapsed`: libcurl total time in seconds for the final hop
- `history`: tuple of redirect responses, without redirect bodies
- `ok`: status below 400
- `encoding`: Content-Type charset, default UTF-8
- `text`: decoded with replacement for invalid sequences (unknown codecs fall back to UTF-8)
- `json(**kwargs)`: standard-library JSON decoding; its exceptions are not wrapped
- `raise_for_status()`: raises `HTTPError` for 4xx/5xx, otherwise returns self

`Headers[name]` joins repeated values with `", "`. Use `get_list("set-cookie")`
for fields that cannot safely be comma-joined. `multi_items()` preserves original
case, order and duplicates. Iteration returns first-seen distinct names.

## Session lifetime and cookies

Use `with Session()` and `async with AsyncSession()`. Sync sessions are not safe
for concurrent use. Async sessions belong to one event loop. `max_connections`
limits concurrent request tasks (not a cap on all cached/idle native sockets).
Async close cancels and awaits active and queued requests, then cleans up handles.

Sync `session.cookies` returns a snapshot of Netscape-format libcurl cookie records;
`clear_cookies()` clears the jar. Both session types maintain an in-memory cookie
jar. Async requests share cookies through a libcurl share handle accessed only by
the owning event loop. There is not yet an async cookie-management facade or
persistent cookie-file API. Closing releases native resources; no global libcurl
cleanup is performed because other packages may still use it.

## Exceptions

- `CurlError`: native `code` plus diagnostic text
- `Timeout`, `ConnectionError`, `SSLError`, `TooManyRedirects`: subclasses
- `HTTPError`: explicit HTTP status failure with `.response`
- `ValueError` / `TypeError`: invalid arguments or configured size limit exceeded
- `NotImplementedError`: unsupported native argument/info type
- `RuntimeError`: closed or busy handle/session or wrong event loop

Exceptions from Python callbacks are captured before crossing the native boundary,
then re-raised after libcurl returns. Cancellation removes an easy handle from its
multi handle before cleaning up Python-owned buffers.

## Low-level Curl

`Curl.setopt(option, value)` returns self. `perform()` blocks. `getinfo(info)`
returns copied strings, numeric values or owned list copies. `reset()` releases
option memory while preserving libcurl's connection cache, DNS cache and cookies.
`close()` is idempotent. Never share a handle concurrently or mutate it in callbacks.

Supported marshalling:

- LONG/VALUES: Python int / IntEnum within native signed-long range
- OFF_T: signed 64-bit integer
- STRINGPOINT: str (UTF-8), bytes without NUL, or None
- SLISTPOINT: iterable of str/bytes without NUL, or None to clear
- BLOB: str/bytes, copied by libcurl
- POSTFIELDS/COPYPOSTFIELDS: str/bytes with binary-safe automatic size
- WRITEFUNCTION/HEADERFUNCTION: callback(bytes) → None or consumed count
- READFUNCTION: callback(max_bytes) → bytes, no longer than requested
- XFERINFOFUNCTION: callback(download_total, downloaded, upload_total, uploaded)
  → truthy to abort; set NOPROGRESS=0 to enable

Scalar/string getinfo values and COOKIELIST/SSL_ENGINES are supported. Raw pointers,
CERTINFO structures, TLS session objects, and socket values are deliberately not
cast generically. Native error buffer and safe default read/write callbacks are
managed internally. Low-level option ordering still follows libcurl semantics;
consult the libcurl manual for the option in use.

`version()` reports linked libcurl and dependency versions; `backend` reports
`"cffi"` or `"ctypes"`. Backend selection happens once at import.

## Coverage and limitations

This is an alpha, not "all of libcurl". Generated enums are not a feature-coverage
claim. Unsupported interfaces include custom debug/socket/SSL callbacks, raw
userdata, public multi/share configuration, URL API, WebSockets, connect-only
send/receive, curl MIME API, and advanced certificate/socket getinfo structures.
Multipart is encoded in Python, not through curl MIME. Uploads are buffered at the
high level; low-level read callbacks permit streaming. No retries, HTTP cache,
iterator streaming, HTTP/2 push interface, or proxy-auth convenience API yet.

HTTP/2, HTTP/3, compression, TLS and non-HTTP protocol availability depend on the
installed libcurl. No HTTP/2 or HTTP/3 integration tests are presently provided.
Local integration tests cover HTTP/1.1, self-signed HTTPS, and file transfers.
CI targets Linux/macOS; Windows library discovery/ABI is not yet validated.

Async multi integration polls every 10ms rather than using socket readiness
callbacks. This is intentionally simpler but adds latency and polling overhead.
Use a libcurl build with asynchronous/threaded DNS to avoid blocking DNS resolution.

## Security boundaries

Keep system libcurl and its TLS dependencies updated. Verification is enabled by
default; `verify=False` is insecure. Basic auth over plain HTTP exposes credentials.
Proxy environment variables are honored by libcurl; use `proxy=""` to disable them.
Untrusted URLs still require application-specific SSRF protections: http(s)-only
restrictions do **not** prevent connections to loopback/private networks. Low-level
Curl intentionally permits all protocols enabled by your libcurl build. Avoid
VERBOSE/debug output when requests contain secrets. There is no secrets logging
by default.
