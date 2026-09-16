"""Small ABI adapter. All native allocations are owned by the calling Curl object."""

from __future__ import annotations

import ctypes as ct
import os
import re
from ctypes.util import find_library
from typing import Any


class SList(ct.Structure):
    pass


SList._fields_ = [("data", ct.c_char_p), ("next", ct.POINTER(SList))]


class Blob(ct.Structure):
    _fields_ = [("data", ct.c_void_p), ("len", ct.c_size_t), ("flags", ct.c_uint)]


class MessageData(ct.Union):
    _fields_ = [("whatever", ct.c_void_p), ("result", ct.c_int)]


class Message(ct.Structure):
    _fields_ = [("msg", ct.c_int), ("easy_handle", ct.c_void_p), ("data", MessageData)]


CDEF = """
typedef void CURL;
typedef void CURLM;
typedef void CURLSH;
CURLSH *curl_share_init(void);
int curl_share_setopt(CURLSH *, int, ...);
int curl_share_cleanup(CURLSH *);
typedef long long curl_off_t;
struct curl_slist { char *data; struct curl_slist *next; };
struct curl_blob { void *data; size_t len; unsigned int flags; };
struct CURLMsg { int msg; CURL *easy_handle; union { void *whatever; int result; } data; };
int curl_global_init(long flags);
char *curl_version(void);
CURL *curl_easy_init(void);
void curl_easy_cleanup(CURL *);
void curl_easy_reset(CURL *);
int curl_easy_setopt(CURL *, int, ...);
int curl_easy_getinfo(CURL *, int, ...);
int curl_easy_perform(CURL *);
char *curl_easy_strerror(int);
struct curl_slist *curl_slist_append(struct curl_slist *, const char *);
void curl_slist_free_all(struct curl_slist *);
CURLM *curl_multi_init(void);
int curl_multi_add_handle(CURLM *, CURL *);
int curl_multi_remove_handle(CURLM *, CURL *);
int curl_multi_perform(CURLM *, int *);
struct CURLMsg *curl_multi_info_read(CURLM *, int *);
int curl_multi_cleanup(CURLM *);
char *curl_multi_strerror(int);
"""


class Backend:
    def __init__(self) -> None:
        choice = os.environ.get("CURLIGHT_BACKEND", "auto")
        if choice not in {"auto", "cffi", "ctypes"}:
            raise ValueError("CURLIGHT_BACKEND must be auto, cffi, or ctypes")
        library = os.environ.get("CURLIGHT_LIBCURL") or find_library("curl")
        if not library:
            raise ImportError("libcurl not found. Install your system's libcurl runtime library.")
        self.ffi: Any = None
        if choice != "ctypes":
            try:
                from cffi import FFI
            except ImportError:
                if choice == "cffi":
                    raise ImportError("Install curlight[cffi] to select CFFI") from None
            else:
                self.ffi = FFI()
                self.ffi.cdef(CDEF)
        self.name = "cffi" if self.ffi else "ctypes"
        self.null: Any = self.ffi.NULL if self.ffi else None
        self.lib: Any = self.ffi.dlopen(library) if self.ffi else ct.CDLL(library)
        if not self.ffi:
            signatures = {
                "curl_share_init": (ct.c_void_p, []),
                "curl_share_setopt": (ct.c_int, [ct.c_void_p, ct.c_int]),
                "curl_share_cleanup": (ct.c_int, [ct.c_void_p]),
                "curl_global_init": (ct.c_int, [ct.c_long]),
                "curl_version": (ct.c_char_p, []),
                "curl_easy_init": (ct.c_void_p, []),
                "curl_easy_cleanup": (None, [ct.c_void_p]),
                "curl_easy_reset": (None, [ct.c_void_p]),
                "curl_easy_setopt": (ct.c_int, [ct.c_void_p, ct.c_int]),
                "curl_easy_getinfo": (ct.c_int, [ct.c_void_p, ct.c_int]),
                "curl_easy_perform": (ct.c_int, [ct.c_void_p]),
                "curl_easy_strerror": (ct.c_char_p, [ct.c_int]),
                "curl_slist_append": (ct.POINTER(SList), [ct.POINTER(SList), ct.c_char_p]),
                "curl_slist_free_all": (None, [ct.POINTER(SList)]),
                "curl_multi_init": (ct.c_void_p, []),
                "curl_multi_add_handle": (ct.c_int, [ct.c_void_p, ct.c_void_p]),
                "curl_multi_remove_handle": (ct.c_int, [ct.c_void_p, ct.c_void_p]),
                "curl_multi_perform": (ct.c_int, [ct.c_void_p, ct.POINTER(ct.c_int)]),
                "curl_multi_info_read": (ct.POINTER(Message), [ct.c_void_p, ct.POINTER(ct.c_int)]),
                "curl_multi_cleanup": (ct.c_int, [ct.c_void_p]),
                "curl_multi_strerror": (ct.c_char_p, [ct.c_int]),
            }
            for name, (restype, argtypes) in signatures.items():
                fn = getattr(self.lib, name)
                fn.restype, fn.argtypes = restype, argtypes
        code = self.lib.curl_global_init(3)
        if code:
            raise ImportError(f"curl_global_init failed: {code}")
        version = self.string(self.lib.curl_version()).decode()
        match = re.search(r"libcurl/(\d+)\.(\d+)\.(\d+)", version)
        if not match or tuple(map(int, match.groups())) < (7, 85, 0):
            raise ImportError(f"curlight requires libcurl >= 7.85.0; found {version}")
        # Never call global_cleanup: other packages/threads may also own libcurl handles.

    def scalar(self, kind: str, value: int) -> Any:
        if self.ffi:
            return self.ffi.cast(kind, value)
        return {"int": ct.c_int, "long": ct.c_long, "curl_off_t": ct.c_int64}[kind](value)

    def buffer(self, data: bytes) -> Any:
        return self.ffi.new("char[]", data) if self.ffi else ct.create_string_buffer(data)

    def pointer(self, kind: str) -> Any:
        if self.ffi:
            return self.ffi.new(kind + " *")
        typ: Any = {
            "long": ct.c_long,
            "double": ct.c_double,
            "curl_off_t": ct.c_int64,
            "int": ct.c_int,
            "char *": ct.c_char_p,
            "struct curl_slist *": ct.POINTER(SList),
        }[kind]
        return ct.pointer(typ())

    def string(self, ptr: Any) -> bytes:
        if not ptr:
            return b""
        return (
            self.ffi.string(ptr)
            if self.ffi
            else (ptr if isinstance(ptr, bytes) else ct.string_at(ptr))
        )

    def read_memory(self, ptr: Any, length: int) -> bytes:
        return bytes(self.ffi.buffer(ptr, length)) if self.ffi else ct.string_at(ptr, length)

    def write_memory(self, ptr: Any, data: bytes) -> None:
        if self.ffi:
            self.ffi.memmove(ptr, data, len(data))
        else:
            ct.memmove(ptr, data, len(data))

    def callback(self, kind: str, fn: Any) -> Any:
        if kind == "progress":
            if self.ffi:
                return self.ffi.callback(
                    "int(void *, curl_off_t, curl_off_t, curl_off_t, curl_off_t)", fn, error=1
                )
            return ct.CFUNCTYPE(ct.c_int, ct.c_void_p, *([ct.c_int64] * 4))(fn)
        if self.ffi:
            return self.ffi.callback("size_t(char *, size_t, size_t, void *)", fn, error=0)
        return ct.CFUNCTYPE(ct.c_size_t, ct.c_void_p, ct.c_size_t, ct.c_size_t, ct.c_void_p)(fn)

    def blob(self, data: Any, length: int) -> Any:
        if self.ffi:
            return self.ffi.new("struct curl_blob *", {"data": data, "len": length, "flags": 1})
        return ct.pointer(Blob(ct.cast(data, ct.c_void_p), length, 1))

    def slist_values(self, ptr: Any) -> list[bytes]:
        result = []
        while ptr:
            node = ptr[0]
            result.append(self.string(node.data))
            ptr = node.next
        return result

    def address(self, ptr: Any) -> int:
        return int(self.ffi.cast("size_t", ptr)) if self.ffi else int(ptr)


backend = Backend()
