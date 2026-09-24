#!/usr/bin/env python3
"""Transport middleware for vmn ui: compression and the bearer-token check."""
import hmac

from fastapi.middleware.gzip import GZipMiddleware

from version_stamp.ui.responses import GZIP_LEVEL, GZIP_MIN_BYTES

ARTIFACT_SEGMENT = "/artifacts/"


def is_artifact_download(path):
    """Artifacts are served as stored: often already compressed, often huge."""
    return path.startswith("/api/") and ARTIFACT_SEGMENT in path


class SelectiveGZipMiddleware(GZipMiddleware):
    """Gzip at a moderate level, never an artifact download."""

    def __init__(self, app, minimum_size=GZIP_MIN_BYTES, compresslevel=GZIP_LEVEL):
        super().__init__(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and is_artifact_download(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


def bearer_matches(authorization, token):
    """Constant-time ``Authorization: Bearer <token>`` check (any header bytes)."""
    expected = f"Bearer {token}".encode("utf-8")
    given = (authorization or "").encode("utf-8")
    return hmac.compare_digest(given, expected)
