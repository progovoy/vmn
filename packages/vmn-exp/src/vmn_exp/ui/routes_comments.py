"""FastAPI routes for comment threads (docs/plans/13-reports-comments.md §8.1).

Targets are ``run:<app>:<verstr>`` or ``report:<rid>``. Reads need
``viewer``, posting ``editor``; editing or deleting a comment also needs its
author or an admin. Mutations are refused under ``--read-only``.
"""
from fastapi import HTTPException, Request

from vmn_exp.reports import comments
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import EDITOR, VIEWER
from vmn_exp.ui.request_author import author_of, require_author_or_admin
from vmn_exp.ui.routes_reports import RID_RE, check_bools
from vmn_exp.ui.security import safe_app_name, safe_segment


def parse_target(raw):
    """``("run", app, verstr)`` / ``("report", rid)`` of *raw*, or a 400."""
    kind, _, rest = (raw or "").partition(":")
    if kind == "report" and RID_RE.match(rest):
        return ("report", rest)
    if kind == "run":
        app, _, verstr = rest.rpartition(":")
        app = safe_app_name(app)
        if app and verstr and safe_segment(verstr):
            return ("run", app, verstr)
    raise HTTPException(400, f"Invalid comment target {raw!r}")


def register(app, api_prefix, any_exp_storage):
    """*any_exp_storage(ws_name)* returns the workspace's experiment storage."""
    base = f"{api_prefix}/workspaces/{{ws_name}}/comments"

    def _require_rw():
        if app.state.read_only:
            raise HTTPException(403, "Server is read-only")

    def _existing(storage, target, comment_id):
        found = next((c for c in comments.thread(storage, target) if c["id"] == comment_id), None)
        if found is None:
            raise HTTPException(404, f"Comment {comment_id!r} not found")
        return found

    @app.get(base, dependencies=[require(VIEWER)])
    def get_thread_route(ws_name: str, target: str):
        return {"comments": comments.thread(any_exp_storage(ws_name), parse_target(target))}

    @app.post(base, status_code=201, dependencies=[require(EDITOR)])
    def post_comment_route(ws_name: str, request: Request, body: dict = None):
        _require_rw()
        body = body or {}
        target, text = parse_target(body.get("target")), body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(400, "text must be a non-empty string")
        comment_id = comments.add(any_exp_storage(ws_name), target, text,
                                  reply_to=body.get("reply_to"), anchor=body.get("anchor"),
                                  author=author_of(request))
        return {"id": comment_id}

    @app.patch(f"{base}/{{target:path}}/{{comment_id}}", dependencies=[require(EDITOR)])
    def patch_comment_route(ws_name: str, target: str, comment_id: str,
                            request: Request, body: dict = None):
        _require_rw()
        body, parsed = body or {}, parse_target(target)
        check_bools(body, "resolved")
        storage = any_exp_storage(ws_name)
        require_author_or_admin(request, ws_name, _existing(storage, parsed, comment_id)["author"])
        if isinstance(body.get("text"), str):
            comments.edit(storage, parsed, comment_id, body["text"])
        if "resolved" in body:
            comments.resolve(storage, parsed, comment_id, body["resolved"])
        return {}

    @app.delete(f"{base}/{{target:path}}/{{comment_id}}", dependencies=[require(EDITOR)])
    def delete_comment_route(ws_name: str, target: str, comment_id: str, request: Request):
        _require_rw()
        parsed, storage = parse_target(target), any_exp_storage(ws_name)
        require_author_or_admin(request, ws_name, _existing(storage, parsed, comment_id)["author"])
        comments.delete(storage, parsed, comment_id)
        return {}
