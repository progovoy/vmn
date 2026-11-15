#!/usr/bin/env python3
"""The audit log (plan 11 §6.2): control-plane table ``vmn_audit``.

Every request to a mutating API route (any route whose declared role is above
``viewer``) leaves one entry, refused ones included, as do logins. Entries
live in the control plane (backed up, never part of the disposable cache).
An entry's id starts with its zero-padded microsecond timestamp
(:func:`audit_key`), so ids sort by time and retention deletes by id range
(:mod:`~vmn_exp.ui.control_plane_sweep`). Pages and counts run in SQL; the
export streams.
"""
import json

from fastapi import Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from vmn_exp.ui.auth.authz import route_role
from vmn_exp.ui.auth.principal import VIEWER

READ_METHODS = ("GET", "HEAD", "OPTIONS")


def audit_key(ts):
    """The id prefix of entries recorded at *ts*; every earlier entry's id sorts below it."""
    return f"{int(ts * 1e6):020d}"


class AuditLog:
    def __init__(self, store, clock, random):
        self.store = store
        self.clock = clock
        self.random = random

    def record(self, actor, action, actor_name="", **fields):
        ts = self.clock()
        entry_id = f"{audit_key(ts)}-{self.random.token_hex(4)}"
        entry = {"id": entry_id, "ts": ts, "actor": actor, "actor_name": actor_name,
                 "action": action, **fields}
        self.store.put("audit", entry_id, entry)
        return entry

    def record_principal(self, principal, action, **fields):
        if principal is None:
            return self.record("anonymous", action, **fields)
        return self.record(principal.id, action, actor_name=principal.name, **fields)

    def entries(self):
        """All entries, oldest first."""
        return self.store.list("audit")

    def page(self, offset=0, limit=100):
        """Newest first."""
        return self.store.page("audit", offset, limit)

    def count(self):
        return self.store.count("audit")

    def export_lines(self):
        """Every entry as a JSON line, oldest first, read in batches."""
        entries = self.store.scan("audit")  # called here, so it captures the request's org
        return (json.dumps(entry) + "\n" for entry in entries)


def audited_route(method, route):
    if method in READ_METHODS or not isinstance(route, APIRoute):
        return False
    return route_role(route) not in (None, VIEWER)


class AuditRecorder:
    """Plain ASGI (a BaseHTTPMiddleware leaves cyclic garbage per request):
    records a mutating request into ``state.audit`` (when it is set) once its
    response starts, before the start goes out. A failed record sends
    nothing more and raises once the app returns."""

    def __init__(self, app, state):
        self.app = app
        self.state = state

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        failure = None

        async def recording_send(message):
            nonlocal failure
            if failure is not None:
                return
            if message["type"] == "http.response.start":
                try:
                    await self._record(scope, message["status"])
                except Exception as exc:  # noqa: BLE001 -- re-raised below, outside the app
                    failure = exc
                    return
            await send(message)

        await self.app(scope, receive, recording_send)
        if failure is not None:
            raise failure

    async def _record(self, scope, status):
        audit = getattr(self.state, "audit", None)
        route = scope.get("route")
        if audit is None or not audited_route(scope["method"], route):
            return
        request = Request(scope)
        await run_in_threadpool(
            audit.record_principal,
            getattr(request.state, "principal", None),
            f"{request.method} {route.path}",
            path=request.url.path,
            workspace=scope.get("path_params", {}).get("ws_name"),
            status=status,
        )


def install_audit_middleware(app):
    """Install :class:`AuditRecorder` on *app*, recording into ``app.state.audit``.

    Install it before the authenticating middleware, so it runs inside it
    and sees ``request.state.principal``."""
    app.add_middleware(AuditRecorder, state=app.state)
