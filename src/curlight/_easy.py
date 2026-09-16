"""Owned, non-thread-safe easy handles with checked native argument types."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ._backend import backend as b
from .constants import OPTION_KINDS, CurlInfo, CurlOpt
from .exceptions import error_for


class Curl:
    """A reusable libcurl easy handle. Use as a context manager; never share concurrently.

    Strings, integers, blobs, string lists, and write/read/progress callbacks are
    marshalled safely. Native userdata and other callback signatures are rejected.
    """

    def __init__(self) -> None:
        self._handle = b.lib.curl_easy_init()
        if not self._handle:
            raise MemoryError("curl_easy_init failed")
        self._refs: dict[int, Any] = {}
        self._lists: dict[int, Any] = {}
        self._callback_error: BaseException | None = None
        self._active = False
        self._defaults()

    def _defaults(self) -> None:
        self._error = b.buffer(b"\0" * 255)
        self._check(b.lib.curl_easy_setopt(self._handle, int(CurlOpt.ERRORBUFFER), self._error))
        self.setopt(CurlOpt.NOSIGNAL, 1)
        # Never let default libcurl callbacks write to stdout or read stdin.
        self.setopt(CurlOpt.WRITEFUNCTION, lambda data: None)
        self.setopt(CurlOpt.READFUNCTION, lambda size: b"")

    def _require_open(self) -> None:
        if not self._handle:
            raise RuntimeError("Curl is closed")

    def _require_idle(self) -> None:
        self._require_open()
        if self._active:
            raise RuntimeError("Curl is in use")

    def _check(self, code: int) -> None:
        if code:
            message = b.string(self._error) or b.string(b.lib.curl_easy_strerror(code))
            raise error_for(code, message.decode("utf-8", "replace"))

    def setopt(self, option: CurlOpt | int, value: Any) -> Curl:
        """Set a typed option, retaining native memory until reset/close or replacement."""
        self._require_idle()
        opt = int(option)
        kind = OPTION_KINDS.get(opt)
        if opt == int(CurlOpt.ERRORBUFFER):
            raise ValueError("ERRORBUFFER is managed internally")
        ref: Any
        new_list: Any = None
        if kind in {"long", "values", "off_t"}:
            if not isinstance(value, int):
                raise TypeError("integer option requires int or IntEnum")
            import ctypes

            bits = 64 if kind == "off_t" else ctypes.sizeof(ctypes.c_long) * 8
            if not -(1 << (bits - 1)) <= value < (1 << (bits - 1)):
                raise OverflowError(f"option requires a signed {bits}-bit integer")
            ref = b.scalar("curl_off_t" if kind == "off_t" else "long", value)
        elif kind == "stringpoint":
            if value is None:
                ref = b.null
            else:
                data = self._encode(value)
                if b"\0" in data:
                    raise ValueError("NUL in string option")
                ref = b.buffer(data)
        elif kind == "slistpoint":
            if isinstance(value, (str, bytes)):
                raise TypeError("string-list options require an iterable of strings")
            new_list = b.null
            try:
                for item in () if value is None else value:
                    data = self._encode(item)
                    if b"\0" in data:
                        raise ValueError("NUL in string list")
                    ptr = b.lib.curl_slist_append(new_list, data)
                    if not ptr:
                        raise MemoryError("curl_slist_append failed")
                    new_list = ptr
            except BaseException:
                b.lib.curl_slist_free_all(new_list)
                raise
            ref = new_list
        elif kind == "blob":
            data = self._encode(value)
            buf = b.buffer(data)
            ref = b.blob(buf, len(data))
        elif opt in {int(CurlOpt.POSTFIELDS), int(CurlOpt.COPYPOSTFIELDS)}:
            data = self._encode(value)
            self.setopt(CurlOpt.POSTFIELDSIZE_LARGE, len(data))
            ref = b.buffer(data)
        elif opt in {
            int(CurlOpt.WRITEFUNCTION),
            int(CurlOpt.HEADERFUNCTION),
            int(CurlOpt.READFUNCTION),
            int(CurlOpt.XFERINFOFUNCTION),
        }:
            if not callable(value):
                raise TypeError("callback option requires a callable")
            ref = self._callback(opt, value)
        else:
            raise NotImplementedError(f"Option {opt} ({kind}) has no safe marshaller")
        try:
            self._check(b.lib.curl_easy_setopt(self._handle, opt, ref))
        except BaseException:
            if kind == "slistpoint":
                b.lib.curl_slist_free_all(new_list)
            raise
        if opt in self._lists:
            b.lib.curl_slist_free_all(self._lists.pop(opt))
        if kind == "slistpoint":
            self._lists[opt] = new_list
        self._refs[opt] = ref
        return self

    @staticmethod
    def _encode(value: str | bytes) -> bytes:
        if isinstance(value, str):
            return value.encode()
        if isinstance(value, bytes):
            return value
        raise TypeError("expected str or bytes")

    def _callback(self, opt: int, fn: Callable[..., Any]) -> Any:
        if opt == int(CurlOpt.XFERINFOFUNCTION):

            def progress(userdata: Any, *counts: int) -> int:
                try:
                    return int(bool(fn(*counts)))
                except BaseException as exc:
                    self._callback_error = exc
                    return 1

            return b.callback("progress", progress)

        def callback(ptr: Any, size: int, count: int, userdata: Any) -> int:
            length = size * count
            try:
                if opt == int(CurlOpt.READFUNCTION):
                    data = fn(length)
                    if not isinstance(data, bytes) or len(data) > length:
                        raise ValueError("read callback must return bytes no longer than requested")
                    b.write_memory(ptr, data)
                    return len(data)
                result = fn(b.read_memory(ptr, length))
                if result is None:
                    return length
                if not isinstance(result, int) or not 0 <= result <= length:
                    raise ValueError(
                        "write callback must return None or a byte count within the chunk"
                    )
                return result
            except BaseException as exc:
                self._callback_error = exc
                return 0x10000000 if opt == int(CurlOpt.READFUNCTION) else 0

        return b.callback("write", callback)

    def getinfo(self, info: CurlInfo | int) -> Any:
        """Read a scalar/string info or an owned copy of COOKIELIST/SSL_ENGINES."""
        self._require_idle()
        number = int(info)
        kind = {
            0x100000: "char *",
            0x200000: "long",
            0x300000: "double",
            0x600000: "curl_off_t",
        }.get(number & 0xF00000)
        is_list = number in {int(CurlInfo.COOKIELIST), int(CurlInfo.SSL_ENGINES)}
        if is_list:
            kind = "struct curl_slist *"
        if kind is None:
            raise NotImplementedError("Pointer and socket getinfo values are not exposed")
        ptr = b.pointer(kind)
        self._check(b.lib.curl_easy_getinfo(self._handle, number, ptr))
        value = ptr[0]
        if is_list:
            try:
                return [s.decode("utf-8", "replace") for s in b.slist_values(value)]
            finally:
                b.lib.curl_slist_free_all(value)
        if kind == "char *":
            return b.string(value).decode("utf-8", "replace")
        return value

    def perform(self) -> None:
        """Run the transfer; callback exceptions are re-raised on the Python side."""
        self._require_idle()
        self._callback_error = None
        self._error[0] = b"\0"
        self._active = True
        try:
            code = b.lib.curl_easy_perform(self._handle)
        finally:
            self._active = False
        self._finish(code)

    def _finish(self, code: int) -> None:
        if self._callback_error is not None:
            exc, self._callback_error = self._callback_error, None
            raise exc
        self._check(code)

    def reset(self) -> None:
        """Reset options, retaining libcurl's connection cache, DNS cache and cookies."""
        self._require_idle()
        b.lib.curl_easy_reset(self._handle)
        self._release_refs()
        self._defaults()

    def _release_refs(self) -> None:
        for ptr in self._lists.values():
            b.lib.curl_slist_free_all(ptr)
        self._lists.clear()
        self._refs.clear()

    def close(self) -> None:
        if self._handle:
            self._require_idle()
            b.lib.curl_easy_cleanup(self._handle)
            self._handle = b.null
            self._release_refs()

    def __enter__(self) -> Curl:
        self._require_idle()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __del__(self) -> None:
        if getattr(self, "_handle", None) and not getattr(self, "_active", False):
            self.close()


def version() -> str:
    """Return the linked libcurl version and dependency versions."""
    return b.string(b.lib.curl_version()).decode()
