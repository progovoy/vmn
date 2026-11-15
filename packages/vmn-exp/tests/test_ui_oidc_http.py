"""UrllibHttp (the real OIDC transport) against a loopback http.server."""
import http.server
import json
import threading

import pytest

from vmn_exp.ui.auth.oidc_http import UrllibHttp


class _Handler(http.server.BaseHTTPRequestHandler):
    def _answer(self):
        if self.path.startswith("/moved"):
            self.send_response(302)
            self.send_header("Location", "/target")
            self.end_headers()
            return
        body = json.dumps({"issuer": "x", "error": "evil"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _answer

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._answer()

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_redirect_is_refused(server):
    http = UrllibHttp()
    assert http.get_json(server + "/target") == {"issuer": "x", "error": "evil"}
    with pytest.raises(Exception, match="redirect"):
        http.get_json(server + "/moved")
    with pytest.raises(Exception, match="redirect"):
        http.post_form(server + "/moved", {"code": "c"})
