"""Prove the libcurl ABI with no package code or external network dependency."""

import ctypes as ct
from ctypes.util import find_library
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


def test_real_http_get_via_ctypes():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"hello from libcurl"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    lib = ct.CDLL(find_library("curl"))
    lib.curl_global_init.argtypes = [ct.c_long]
    lib.curl_global_init.restype = ct.c_int
    lib.curl_easy_init.argtypes = []
    lib.curl_easy_init.restype = ct.c_void_p
    lib.curl_easy_setopt.argtypes = [ct.c_void_p, ct.c_int]
    lib.curl_easy_setopt.restype = ct.c_int
    lib.curl_easy_perform.argtypes = [ct.c_void_p]
    lib.curl_easy_perform.restype = ct.c_int
    lib.curl_easy_cleanup.argtypes = [ct.c_void_p]
    lib.curl_easy_cleanup.restype = None
    chunks = []

    @ct.CFUNCTYPE(ct.c_size_t, ct.c_void_p, ct.c_size_t, ct.c_size_t, ct.c_void_p)
    def write(data, size, count, userdata):
        chunks.append(ct.string_at(data, size * count))
        return size * count

    assert lib.curl_global_init(3) == 0
    handle = lib.curl_easy_init()
    assert handle
    try:
        url = f"http://127.0.0.1:{server.server_port}/".encode()
        assert lib.curl_easy_setopt(handle, 10002, ct.c_char_p(url)) == 0
        assert lib.curl_easy_setopt(handle, 20011, write) == 0
        assert lib.curl_easy_setopt(handle, 155, ct.c_long(5000)) == 0
        assert lib.curl_easy_perform(handle) == 0
        assert b"".join(chunks) == b"hello from libcurl"
    finally:
        lib.curl_easy_cleanup(handle)
        server.shutdown()
        server.server_close()
        thread.join()
    # Do not globally clean up libcurl while another test/backend may still use it.
