"""FastAPI routes for reports (docs/plans/13-reports-comments.md §8.1).

Under ``/api/v1/workspaces/{ws_name}/reports``; they write storage directly
(``vmn_exp.reports``), like ``routes_models``. Mutations are refused under
``--read-only``; reads need ``viewer``, writes ``editor``, delete ``admin``.
"""
import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from vmn_exp.reports import published, store
from vmn_exp.reports.log import set_archived, set_pinned, set_title
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import ADMIN, EDITOR, VIEWER
from vmn_exp.ui.reports_publish import validate_publish
from vmn_exp.ui.request_author import author_of

RID_RE = re.compile(r"^r[a-z2-7]{1,64}$")


def register(app, api_prefix, any_exp_storage):
    """*any_exp_storage(ws_name)* returns the workspace's experiment storage."""
    base = f"{api_prefix}/workspaces/{{ws_name}}/reports"

    def _require_rw():
        if app.state.read_only:
            raise HTTPException(403, "Server is read-only")

    def _report(ws_name, rid):
        if not RID_RE.match(rid):
            raise HTTPException(400, f"Invalid report id {rid!r}")
        storage = any_exp_storage(ws_name)
        report = store.get(storage, rid)
        if report is None:
            raise HTTPException(404, f"Report {rid!r} not found")
        return storage, report

    def _revision(ws_name, rid, n):
        storage, _ = _report(ws_name, rid)
        found = store.revision(storage, rid, n)
        if found is None:
            raise HTTPException(404, f"Revision {n} of {rid!r} not found")
        return storage, found

    @app.get(base, dependencies=[require(VIEWER)])
    def list_reports_route(ws_name: str, archived: bool = False):
        reports = store.list_reports(any_exp_storage(ws_name))
        rows = [{k: v for k, v in r.items() if k != "body"} for r in reports]
        return {"reports": [r for r in rows if bool(r.get("archived")) == archived]}

    @app.post(base, status_code=201, dependencies=[require(EDITOR)])
    def create_report_route(ws_name: str, request: Request, body: dict = None):
        _require_rw()
        title, text = (body or {}).get("title"), (body or {}).get("body", "")
        if not isinstance(title, str) or not title.strip() or not isinstance(text, str):
            raise HTTPException(400, "title (non-empty) and body must be strings")
        rid = store.create(any_exp_storage(ws_name), title, text, actor=author_of(request))
        return {"rid": rid, "rev": 1}

    @app.get(f"{base}/{{rid}}", dependencies=[require(VIEWER)])
    def get_report_route(ws_name: str, rid: str):
        storage, report = _report(ws_name, rid)
        return {**report, "revisions": store.revisions(storage, rid)}

    @app.get(f"{base}/{{rid}}/revisions/{{n}}", dependencies=[require(VIEWER)])
    def get_revision_route(ws_name: str, rid: str, n: int):
        storage, found = _revision(ws_name, rid, n)
        return {**found, "data": published.panel_ids(storage, rid, n)}

    @app.get(f"{base}/{{rid}}/revisions/{{n}}/data/{{panel}}", dependencies=[require(VIEWER)])
    def get_panel_data_route(ws_name: str, rid: str, n: int, panel: str):
        storage, _ = _revision(ws_name, rid, n)
        data = published.panel_data(storage, rid, n, panel)
        if data is None:
            raise HTTPException(404, f"No published data for panel {panel!r}")
        return data

    @app.post(f"{base}/{{rid}}/revisions", status_code=201, dependencies=[require(EDITOR)])
    def save_revision_route(ws_name: str, rid: str, request: Request, body: dict = None):
        _require_rw()
        body = body or {}
        base_rev, text = body.get("base"), body.get("body")
        if not isinstance(base_rev, int) or base_rev < 0 or not isinstance(text, str):
            raise HTTPException(400, "base (integer) and body (string) are required")
        storage, _ = _report(ws_name, rid)
        result = store.save(storage, rid, base_rev, text, str(body.get("message") or ""),
                            actor=author_of(request))
        if isinstance(result, store.Conflict):
            return JSONResponse({"rev": result.rev, "body": result.body,
                                 "author": result.author}, status_code=409)
        return {"rev": result}

    @app.post(f"{base}/{{rid}}/publish", dependencies=[require(EDITOR)])
    def publish_route(ws_name: str, rid: str, request: Request, body: dict = None):
        _require_rw()
        storage, _ = _report(ws_name, rid)
        rev, data = validate_publish(storage, body or {})
        if store.revision(storage, rid, rev) is None:
            raise HTTPException(404, f"Revision {rev} of {rid!r} not found")
        published.publish(storage, rid, rev, data, actor=author_of(request))
        return {"rev": rev}

    @app.patch(f"{base}/{{rid}}", dependencies=[require(EDITOR)])
    def patch_report_route(ws_name: str, rid: str, request: Request, body: dict = None):
        _require_rw()
        storage, _ = _report(ws_name, rid)
        actor = author_of(request)
        setters = {"title": set_title, "archived": set_archived, "pinned": set_pinned}
        for field, setter in setters.items():
            if field in (body or {}):
                setter(storage, rid, body[field], actor=actor)
        return {}

    @app.delete(f"{base}/{{rid}}", dependencies=[require(ADMIN)])
    def delete_report_route(ws_name: str, rid: str):
        _require_rw()
        storage, _ = _report(ws_name, rid)
        store.delete(storage, rid)
        return {}
