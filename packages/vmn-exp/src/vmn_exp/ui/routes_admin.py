"""Admin routes on the control plane: API tokens and the audit log."""
import json
from dataclasses import asdict

from fastapi import HTTPException, Request
from fastapi.responses import Response

from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import ADMIN
from vmn_exp.ui.auth.tokens import TokenService
from vmn_exp.ui.http_params import clamp_page


def public_record(record):
    doc = asdict(record)
    doc.pop("secret_hash")
    return doc


def _control_plane(app):
    cp = getattr(app.state, "control_plane", None)
    if cp is None:
        raise HTTPException(503, "This server has no control plane (start it with --config)")
    return cp


def _token_body(body):
    name, roles, ttl = body.get("name"), body.get("roles", {}), body.get("ttl_sec")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(422, "Field 'name' is required")
    if not isinstance(roles, dict):
        raise HTTPException(422, "Field 'roles' must map workspaces to roles")
    if ttl is not None and (not isinstance(ttl, (int, float)) or ttl <= 0):
        raise HTTPException(422, "Field 'ttl_sec' must be a positive number")
    return name.strip(), roles, ttl


def register(app, api_prefix):
    def _tokens():
        return TokenService(_control_plane(app))

    @app.get(f"{api_prefix}/tokens", dependencies=[require(ADMIN)])
    def list_tokens():
        return [public_record(r) for r in _tokens().list()]

    @app.post(f"{api_prefix}/tokens", status_code=201, dependencies=[require(ADMIN)])
    def create_token(request: Request, body: dict):
        name, roles, ttl = _token_body(body)
        principal = request.state.principal
        try:
            token, record = _tokens().create(
                name, roles, owner=principal.id if principal else "", ttl_sec=ttl)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"token": token, "record": public_record(record)}

    @app.delete(f"{api_prefix}/tokens/{{token_id}}", status_code=204,
                dependencies=[require(ADMIN)])
    def revoke_token(token_id: str):
        if not _tokens().revoke(token_id):
            raise HTTPException(404, f"Unknown token {token_id!r}")

    @app.get(f"{api_prefix}/audit", dependencies=[require(ADMIN)])
    def audit_page(offset: int = 0, limit: int = 100):
        _control_plane(app)
        offset, limit = clamp_page(offset, limit)
        audit = app.state.audit
        return {"entries": audit.page(offset, limit), "total": len(audit.entries()),
                "offset": offset}

    @app.get(f"{api_prefix}/audit/export", dependencies=[require(ADMIN)])
    def audit_export():
        _control_plane(app)
        body = "".join(json.dumps(e) + "\n" for e in app.state.audit.entries())
        return Response(body, media_type="application/x-ndjson",
                        headers={"Content-Disposition": 'attachment; filename="audit.jsonl"'})
