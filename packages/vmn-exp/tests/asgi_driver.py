"""Drive an ASGI app as uvicorn serves it: plain ``http`` scopes on one
long-lived event loop, with no test client's portal, thread or streams in
between (starlette's TestClient leaves cyclic garbage of its own per request)."""
import asyncio
import urllib.parse


def http_get_scope(url, headers=()):
    """The scope uvicorn builds for ``GET url``: ``path`` is the
    percent-decoded raw path and is *not* dot-segment normalized."""
    raw_path, _, query = url.partition("?")
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": urllib.parse.unquote(raw_path),
        "raw_path": raw_path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(b"host", b"127.0.0.1:8265"), (b"accept-encoding", b"gzip, deflate")] + list(headers),
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 8265),
    }


async def asgi_get(app, url, headers=()):
    """``(status, body)`` of ``GET url``. As a server does, receive gives the
    request once, then blocks until the response is complete and reports the
    client gone: an app that watches for a disconnect while it streams would
    otherwise spin on an always-ready receive."""
    out = {"status": None, "body": b""}
    requested = False
    responded = asyncio.Event()

    async def receive():
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await responded.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
        elif message["type"] == "http.response.body":
            out["body"] += message.get("body", b"")
            if not message.get("more_body", False):
                responded.set()

    await app(http_get_scope(url, headers), receive, send)
    return out["status"], out["body"]


class AsgiDriver:
    """Serves GETs to *app* on one event loop kept for the driver's life."""

    def __init__(self, app):
        self.app = app
        self.loop = asyncio.new_event_loop()

    def get(self, url, headers=()):
        return self.loop.run_until_complete(asgi_get(self.app, url, headers))

    def close(self):
        self.loop.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
