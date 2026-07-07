"""Regression: the local API client must ignore system proxy settings.

Field bug: with HTTP_PROXY set (corporate machines), httpx routed 127.0.0.1 calls through
the proxy, which rejected them with 403 while the service was perfectly reachable in a
browser. The client is constructed with trust_env=False so localhost is never proxied.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from reportflow.ui.api_client import ApiClient


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server API
        body = json.dumps({"status": "ok", "version": "test"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def local_http_server():
    server = HTTPServer(("127.0.0.1", 0), _Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def test_client_ignores_proxy_env(local_http_server, monkeypatch):
    # A proxy address that is guaranteed dead: nothing listens on this port.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        monkeypatch.setenv(var, f"http://127.0.0.1:{dead_port}")

    client = ApiClient(local_http_server)
    try:
        # If the proxy env were honored, this would fail (dead proxy). It must succeed.
        assert client.health()["status"] == "ok"
    finally:
        client.close()


def test_unreachable_error_names_the_url():
    client = ApiClient("http://127.0.0.1:1", timeout=0.5)
    try:
        from reportflow.ui.api_client import ApiError

        with pytest.raises(ApiError, match=r"127\.0\.0\.1:1"):
            client.health()
    finally:
        client.close()
