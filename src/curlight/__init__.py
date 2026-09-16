"""Pythonic libcurl bindings with CFFI and a stdlib ctypes fallback."""
from ._backend import backend as _backend
from ._easy import Curl, version
from .constants import CurlAuth, CurlCode, CurlInfo, CurlOpt, HttpVersion
from .exceptions import ConnectionError, CurlError, HTTPError, SSLError, Timeout, TooManyRedirects
from .models import Headers, Response
from .session import Session, get, request

__version__ = "0.1.0"
backend = _backend.name

__all__ = [
    "Curl", "CurlAuth", "CurlCode", "CurlInfo", "CurlOpt", "HttpVersion",
    "ConnectionError", "CurlError", "HTTPError", "SSLError", "Timeout", "TooManyRedirects",
    "Headers", "Response", "Session", "get", "request", "version", "backend",
]
