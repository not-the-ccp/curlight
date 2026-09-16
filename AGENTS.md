# curlight project guidance

- Use .venv for Python tooling. Test ctypes and CFFI in separate processes.
- Run Ruff, mypy, both pytest backend suites and build/twine checks before completion.
- Never pass untyped pointers or guessed callback signatures to libcurl.
- Native buffers/callbacks must outlive every native reference; remove handles from
  multi before resetting or closing them. Never globally clean up libcurl.
- Prefer local HTTP/TLS fixtures; tests must not depend on public network services.
- Keep docs honest about alpha status and incomplete native interface coverage.
- Use gh for GitHub operations. Do not publish to PyPI without explicit approval.
