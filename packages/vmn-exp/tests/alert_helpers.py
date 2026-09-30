"""A local HTTP server that records the webhook POSTs an alert sink makes."""
import http.server
import json
import socket
import threading
import time


class WebhookReceiver:
    """Collects ``(path, headers, json_body)`` for every POST it receives."""

    def __init__(self, status=200):
        self.requests = []
        self.status = status
        receiver = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                receiver.requests.append(
                    (self.path, dict(self.headers), json.loads(body or b"null"))
                )
                self.send_response(receiver.status)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}/hook"

    @property
    def bodies(self):
        return [body for _, _, body in self.requests]

    def wait_for(self, count, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and len(self.requests) < count:
            time.sleep(0.02)
        return len(self.requests) >= count

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


def dead_url():
    """A URL on a port nothing listens on: connections are refused."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/hook"
