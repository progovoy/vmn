#!/usr/bin/env python3
"""The web bundle: hashed assets cached forever, the SPA shell revalidated.

Vite names every file under ``assets/`` by its content hash, so a browser may
keep them for a year; ``index.html`` names the current hashes and must be
revalidated on each load. Paths under ``/api`` never fall back to the shell —
an unknown endpoint is a JSON 404, not a 200 page of HTML.
"""
import os

from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from version_stamp.ui.security import within

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


class ImmutableStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            response.headers["Cache-Control"] = IMMUTABLE
        return response


def _is_api(full_path):
    return full_path == "api" or full_path.startswith("api/")


def _api_not_found():
    return JSONResponse({"detail": "Not Found"}, status_code=404)


def mount_static(app, static_dir):
    """Serve the bundle in *static_dir*; unknown ``/api`` paths 404 either way."""
    if not os.path.isdir(static_dir):

        @app.get("/api/{rest:path}", include_in_schema=False)
        def api_not_found(rest: str):
            return _api_not_found()

        return

    app.mount(
        "/assets",
        ImmutableStaticFiles(directory=os.path.join(static_dir, "assets")),
        name="assets",
    )

    # History-API fallback: any non-API route is a client-side route — serve
    # the SPA shell and let the router resolve it.
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if _is_api(full_path):
            return _api_not_found()
        # ``full_path`` is decoded but not normalized: ``//etc/passwd`` and
        # ``..%2f`` walks must resolve inside the bundle or fall back to the shell.
        candidate = os.path.join(static_dir, full_path)
        if full_path and within(static_dir, candidate) and os.path.isfile(candidate):
            return FileResponse(candidate, headers={"Cache-Control": REVALIDATE})
        return FileResponse(
            os.path.join(static_dir, "index.html"), headers={"Cache-Control": REVALIDATE}
        )
