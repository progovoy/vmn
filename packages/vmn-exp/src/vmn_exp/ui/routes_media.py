#!/usr/bin/env python3
"""``GET .../experiments/{verstr}/table/{path}`` — a logged table, paged.

``run.log_table`` stores a columnar JSON artifact (see
:mod:`vmn_exp.core.tables`); this answers a row-major page of it::

    ?offset=0&limit=100&sort=<column>&order=asc|desc
    -> {"columns": [{"name", "type"}], "rows": [[...]], "total", "offset",
        "truncated"}

Sorting is server-side over the whole table (at most 10k rows). Images need no
route of their own: the artifact download serves them as ``image/png``.

``GET .../experiments/{verstr}/histograms/{name}`` answers one histogram key's
served steps, ``{"name", "steps": [{"step", "bins", "counts"}], "total"}``
(the run detail lists the names in ``histograms_total``; see
:mod:`vmn_exp.ui.readers.histograms`).
"""
import json

from fastapi import HTTPException, Request

from vmn_exp.core.tables import table_page
from vmn_exp.storage.files import valid_artifact_path
from vmn_exp.ui.http_params import clamp_page
from vmn_exp.ui.readers.experiment_detail import run_media
from vmn_exp.ui.readers.histograms import histogram_of
from vmn_exp.ui.responses import json_response

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


def register(app, prefix, storage_for, segment):
    """Add the route; *storage_for(ws_name, app_tag)* → ``(storage, app_name, ...)``,
    *segment(verstr)* returns a URL verstr or raises a 400."""

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
        segment(verstr)
        if not valid_artifact_path(path):
            raise HTTPException(400, "Invalid table path")
        doc = load_table(storage, app_name, verstr, path)
        offset, limit = clamp_page(offset, limit)
        try:
            page = table_page(doc, offset, limit, sort=sort or None, order=order)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return json_response(page, request=request)

    @app.get(
        f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}"
        "/experiments/{verstr}/histograms/{name:path}"
    )
    def experiment_histogram(request: Request, ws_name: str, app_tag: str, verstr: str, name: str):
        storage, app_name = storage_for(ws_name, app_tag)[:2]
        segment(verstr)
        media = run_media(storage, app_name, verstr)
        if media is None:
            raise HTTPException(404, f"Experiment {verstr} not found")
        found = histogram_of(media, name)
        if found is None:
            raise HTTPException(404, f"Histogram {name} not found")
        return json_response(found, request=request)
