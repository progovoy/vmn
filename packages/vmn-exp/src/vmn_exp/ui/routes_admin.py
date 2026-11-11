"""Admin routes on the control plane: API tokens and the audit log."""
from dataclasses import asdict

from fastapi import HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import ADMIN
from vmn_exp.ui.auth.sessions import SessionService
from vmn_exp.ui.http_params import clamp_page, page_of


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


def register(app, api_prefix, wall_clock):
    """The routes; *wall_clock* (epoch seconds) times the sessions they close."""
    def _tokens():
        _control_plane(app)
        return app.state.token_service

    @app.get(f"{api_prefix}/tokens", dependencies=[require(ADMIN)])
    def list_tokens(response: Response, offset: int = 0, limit: int = None):
        page, total = page_of(_tokens().list(), offset, limit)
        if total is not None:
            response.headers["X-Total-Count"] = str(total)
        return [public_record(r) for r in page]

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

    @app.delete(f"{api_prefix}/tokens", dependencies=[require(ADMIN)])
    def revoke_owner(owner: str = ""):
        """Cut one user off: every token they own and every browser session."""
        if not owner:
            raise HTTPException(422, "Query parameter 'owner' is required")
        return {"tokens": _tokens().revoke_owner(owner),
                "sessions": SessionService(_control_plane(app), wall_clock).close_principal(owner)}

    @app.get(f"{api_prefix}/audit", dependencies=[require(ADMIN)])
    def audit_page(offset: int = 0, limit: int = 100):
        _control_plane(app)
        offset, limit = clamp_page(offset, limit)
        audit = app.state.audit
        return {"entries": audit.page(offset, limit), "total": audit.count(),
                "offset": offset}

    @app.get(f"{api_prefix}/audit/export", dependencies=[require(ADMIN)])
    def audit_export():
        _control_plane(app)
        return StreamingResponse(
            app.state.audit.export_lines(), media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="audit.jsonl"'})
