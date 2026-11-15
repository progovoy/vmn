#!/usr/bin/env python3
"""Transport middleware for vmn-exp ui: compression, request gates and the bearer-token check."""
import hmac

from fastapi import Request
from fastapi.middleware.gzip import GZipMiddleware

from vmn_exp.ui.responses import GZIP_LEVEL, GZIP_MIN_BYTES

# A run's stored files: its user artifacts and vmn's outputs.
FILE_SEGMENTS = ("/artifacts/", "/outputs/")


def is_artifact_download(path):
    """Stored files are served as stored: often already compressed, often huge."""
    return path.startswith("/api/") and any(s in path for s in FILE_SEGMENTS)


class SelectiveGZipMiddleware(GZipMiddleware):
    """Gzip at a moderate level, never an artifact download."""

    def __init__(self, app, minimum_size=GZIP_MIN_BYTES, compresslevel=GZIP_LEVEL):
        super().__init__(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and is_artifact_download(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


class RequestGate:
    """Plain ASGI around ``await check(request)``: the response it answers is
    sent instead of the request, ``None`` passes the request on. A
    BaseHTTPMiddleware would leave cyclic garbage per request."""

    def __init__(self, app, check):
        self.app = app
        self.check = check

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        refusal = await self.check(Request(scope, receive))
        await (self.app if refusal is None else refusal)(scope, receive, send)


def bearer_matches(authorization, token):
    """Constant-time ``Authorization: Bearer <token>`` check (any header bytes)."""
    expected = f"Bearer {token}".encode()
    given = (authorization or "").encode("utf-8")
    return hmac.compare_digest(given, expected)
