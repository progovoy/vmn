#!/usr/bin/env python3
"""``/auth/login``, ``/auth/callback``, ``/auth/logout`` and the device flow
(``/auth/device/start``, ``/auth/device/token``, for ``vmn-exp login``)."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from vmn_exp.ui.auth.device import DeviceFlow, DeviceFlowError
from vmn_exp.ui.auth.oidc import SESSION_COOKIE, OIDCError


def _audit_login(request, principal, method):
    audit = getattr(request.app.state, "audit", None)
    if audit is not None:
        audit.record_principal(principal, "login", method=method)


def oidc_router(oidc):
    router = APIRouter()
    device = DeviceFlow(oidc)

    @router.get("/auth/login")
    def _login():
        try:
            url = oidc.login_url()
        except OIDCError as exc:
            return JSONResponse({"detail": f"Identity provider: {exc}"}, status_code=502)
        return RedirectResponse(url, status_code=302)

    @router.get("/auth/callback")
    def _callback(request: Request, code: str = "", state: str = ""):
        try:
            session_id = oidc.complete(code, state)
        except OIDCError as exc:
            return JSONResponse({"detail": f"Login failed: {exc}"}, status_code=400)
        _audit_login(request, oidc.sessions.principal(session_id), "browser")
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

    @router.post("/auth/device/start")
    def _device_start():
        try:
            return device.start()
        except OIDCError as exc:
            return JSONResponse({"detail": f"Identity provider: {exc}"}, status_code=502)

    @router.post("/auth/device/token")
    def _device_token(request: Request, body: dict):
        try:
            token, record, principal = device.poll(body.get("device_code"))
        except DeviceFlowError as exc:
            return JSONResponse({"error": exc.code}, status_code=400)
        _audit_login(request, principal, "device")
        return {"token": token, "token_id": record.id, "expires_at": record.expires_at}

    return router
