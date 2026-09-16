"""End-to-end tests through the installed package's public entry point."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import curlight


def test_get_local_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"hello from curlight"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = curlight.get(f"http://127.0.0.1:{server.server_port}/", timeout=5)
        assert response.status_code == 200
        assert response.content == b"hello from curlight"
        assert response.text == "hello from curlight"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
