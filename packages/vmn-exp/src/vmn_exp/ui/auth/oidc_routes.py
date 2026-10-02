#!/usr/bin/env python3
"""``/auth/login``, ``/auth/callback`` and ``/auth/logout`` for OIDC."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from vmn_exp.ui.auth.oidc import SESSION_COOKIE, OIDCError


def oidc_router(oidc):
    router = APIRouter()

    @router.get("/auth/login")
    def _login():
        try:
            url = oidc.login_url()
        except OIDCError as exc:
            return JSONResponse({"detail": f"Identity provider: {exc}"}, status_code=502)
        return RedirectResponse(url, status_code=302)

    @router.get("/auth/callback")
    def _callback(code: str = "", state: str = ""):
        try:
            session_id = oidc.complete(code, state)
        except OIDCError as exc:
            return JSONResponse({"detail": f"Login failed: {exc}"}, status_code=400)
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=oidc.sessions.ttl_sec,
            path="/",
            httponly=True,
            secure=True,
            samesite="lax",
        )
        return resp

    @router.post("/auth/logout")
    def _logout(request: Request):
        oidc.sessions.close(request.cookies.get(SESSION_COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return resp

    return router
