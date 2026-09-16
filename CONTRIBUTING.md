# Contributing

Use one project-local virtual environment. Install libcurl 7.85+, and OpenSSL CLI
for local TLS tests. Curl development headers and a C compiler are needed only to
regenerate constants.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check src tests tools examples
.venv/bin/ruff format --check src tests tools examples
.venv/bin/mypy
CURLIGHT_BACKEND=ctypes .venv/bin/pytest --cov=curlight --cov-report=term-missing
CURLIGHT_BACKEND=cffi .venv/bin/pytest
.venv/bin/python -m build
.venv/bin/twine check dist/*
```

Tests use loopback servers, not external services. Add regression tests for both
backends whenever changing native argument types or lifetime handling. Do not
infer pointer types solely from numeric CURLOPT ranges; use OPTION_KINDS and
explicit safe marshallers. Never let a callback exception escape into C.

## Layout

- `_backend.py`: ABI declarations, ctypes/CFFI primitives
- `_easy.py`: easy handle ownership, type marshalling and callback guards
- `session.py`: shared request/redirect state machine and synchronous facade
- `async_session.py`: cooperative multi loop, cancellation and cookie sharing
- `models.py`, `multipart.py`: Python value objects and multipart encoding
- `constants.py`: generated enums and semantic option kinds

Regenerate constants on a deliberate libcurl baseline update:

```sh
python tools/gen_constants.py
ruff format src/curlight/constants.py
```

The generator compiles a temporary C probe against installed headers; it is not
run at installation. Inspect enum/option-table diffs and run both backends.

## Releases

The release workflow builds tested artifacts only; it does not publish to PyPI.
Before publishing: review security and compatibility, update versions/changelog,
run CI, inspect wheel/sdist contents, and explicitly configure a trusted publisher.
Never put publishing credentials in this repo.
