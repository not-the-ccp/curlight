# Changelog

## 0.1.0 — Unreleased

- Add CFFI ABI backend with stdlib ctypes fallback and runtime version validation.
- Add owned easy handles, typed options, callback guards and binary-safe bodies.
- Add HTTP sessions, verb helpers, query/form/JSON/multipart requests, auth,
  TLS/proxy controls, cookie persistence and connection reuse.
- Add response models, duplicate-preserving headers, redirect history and typed errors.
- Add bounded buffering and streaming download sinks.
- Add AsyncSession using libcurl multi, shared cookies and cancellation cleanup.
- Generate constants and semantic option metadata from libcurl 8.14.1 headers.
- Add local HTTP/TLS integration tests, backend matrix CI and packaging checks.

This is an initial alpha. See docs/api.md for unsupported native interfaces and
platform/performance limitations. No PyPI release has been published.
