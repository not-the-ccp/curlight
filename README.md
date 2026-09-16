# curlight

Pythonic HTTP sessions over the **real libcurl**, with CFFI and a stdlib-only
ctypes fallback. Early development (0.1.0); not a drop-in replacement for PycURL.

Requires Python 3.10+ and a system libcurl 7.85+ runtime. No curl headers or C
compiler are required by users. TLS certificate verification is enabled by default.

```sh
# Debian / Ubuntu
sudo apt install libcurl4
python -m pip install -e '.[dev]'
```

```python
import curlight

response = curlight.get("https://example.com", timeout=10)
response.raise_for_status()
print(response.text)
```

Backend selection: `CURLIGHT_BACKEND=auto` (default), `cffi`, or `ctypes`.
Auto prefers CFFI when installed; otherwise uses ctypes. Set `CURLIGHT_LIBCURL`
to an explicit shared-library path if system discovery fails.

Development checks:

```sh
CURLIGHT_BACKEND=ctypes python -m pytest
CURLIGHT_BACKEND=cffi python -m pytest
```

The test suite uses local servers, not public services. Native interfaces not
safely marshalled by the binding raise `NotImplementedError`; generated constants
do not imply that every pointer or callback signature is supported.

MIT licensed. See [LICENSE](LICENSE).
