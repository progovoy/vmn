#!/usr/bin/env python3
"""``GET .../experiments/{verstr}/table/{path}`` — a logged table, paged.

``run.log_table`` stores a columnar JSON artifact (see
:mod:`vmn_exp.core.tables`); this answers a row-major page of it::

    ?offset=0&limit=100&sort=<column>&order=asc|desc
    -> {"columns": [{"name", "type"}], "rows": [[...]], "total", "offset",
        "truncated"}

Sorting is server-side over the whole table (at most 10k rows). Images need no
route of their own: the artifact download serves them as ``image/png``.
"""
import json

from fastapi import HTTPException, Request

from vmn_exp.core.tables import table_page
from vmn_exp.storage.files import valid_artifact_path
from vmn_exp.ui.http_params import clamp_page
from vmn_exp.ui.responses import json_response
from vmn_exp.ui.security import safe_segment

DEFAULT_TABLE_PAGE = 100


def load_table(storage, app_name, verstr, path):
    """The table document artifact *path*, or an HTTPException."""
    local = storage.artifact_local_path(app_name, verstr, path)
    if not local:
        raise HTTPException(404, f"Table {path} not found")
    try:
        with open(local, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        raise HTTPException(400, f"{path} is not a logged table") from None
    if not isinstance(doc, dict) or not {"columns", "data", "rows"} <= doc.keys():
        raise HTTPException(400, f"{path} is not a logged table")
    return doc


def register(app, prefix, storage_for):
    """Add the route; *storage_for(ws_name, app_tag)* → ``(storage, app_name, ...)``."""

    @app.get(
        f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}"
        "/experiments/{verstr}/table/{path:path}"
    )
    def experiment_table(
        request: Request,
        ws_name: str,
        app_tag: str,
        verstr: str,
        path: str,
        offset: int = 0,
        limit: int = DEFAULT_TABLE_PAGE,
        sort: str = None,
        order: str = "asc",
    ):
        storage, app_name = storage_for(ws_name, app_tag)[:2]
        if not safe_segment(verstr) or not valid_artifact_path(path):
            raise HTTPException(400, "Invalid table path")
        doc = load_table(storage, app_name, verstr, path)
        offset, limit = clamp_page(offset, limit)
        try:
            page = table_page(doc, offset, limit, sort=sort or None, order=order)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return json_response(page, request=request)
