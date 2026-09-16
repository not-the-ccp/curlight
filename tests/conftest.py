from __future__ import annotations

import gzip
import json
import ssl
import subprocess
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        status, fields = 200, []
        body = json.dumps(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers),
                "body": self.rfile.read(int(self.headers.get("Content-Length", 0))).decode(
                    "latin-1"
                ),
                "port": self.client_address[1],
            }
        ).encode()
        if parts.path == "/delay":
            time.sleep(float(query.get("seconds", ["0.15"])[0]))
        elif parts.path == "/redirect":
            status = int(query.get("status", ["302"])[0])
            fields.append(("Location", query.get("to", ["/echo"])[0]))
            body = b"redirect body"
        elif parts.path == "/cookies":
            fields += [("Set-Cookie", "one=1; Path=/"), ("Set-Cookie", "two=2; Path=/")]
        elif parts.path == "/gzip":
            body = gzip.compress(b"compressed response")
            fields.append(("Content-Encoding", "gzip"))
        elif parts.path == "/large":
            body = b"x" * 100000
        elif parts.path == "/status":
            status = int(query.get("code", ["404"])[0])
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in fields:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            with suppress(BrokenPipeError, ConnectionResetError, ssl.SSLError):
                self.wfile.write(body)

    do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = do_GET


@pytest.fixture
def server_factory():
    servers = []

    def start(context=None):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        if context:
            server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"{'https' if context else 'http'}://127.0.0.1:{server.server_port}"

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def base_url(server_factory):
    return server_factory()


@pytest.fixture(scope="session")
def tls_cert(tmp_path_factory):
    path = tmp_path_factory.mktemp("tls")
    cert, key = path / "cert.pem", path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


@pytest.fixture
def tls_url(server_factory, tls_cert):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(*map(str, tls_cert))
    return server_factory(context)
