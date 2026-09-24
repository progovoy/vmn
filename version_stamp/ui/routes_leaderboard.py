#!/usr/bin/env python3
"""The leaderboard routes: ``.../experiments`` pages and ``.../experiments-facets``.

Both answer from the app's current index snapshot through a
:class:`~version_stamp.ui.leaderboard_cache.LeaderboardCache`, so a poll costs
a page slice. The list's ``ETag`` is known before any row is touched (index
generation, parameters, and the time bucket while runs are live): a client
repeating it gets an empty ``304`` without the payload ever being built.
"""
from fastapi import HTTPException, Request

from version_stamp.core.experiment_query import QueryError
from version_stamp.ui.readers.experiments import ORDERS
from version_stamp.ui.responses import json_response, not_modified


def _clamped(offset, limit, max_page):
    limit = None if limit is None else max(0, min(int(limit), max_page))
    return max(0, int(offset or 0)), limit


def register(app, api_prefix, inputs, cache):
    """*inputs(ws_name, app_tag)* -> ``(snapshot, metrics schema)``, raising
    the route's HTTP errors for a bad workspace or app."""
    base = f"{api_prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}"

    @app.get(f"{base}/experiments")
    def list_experiments(
        request: Request,
        ws_name: str,
        app_tag: str,
        sort: str = None,
        last: int = None,
        offset: int = 0,
        limit: int = None,
        status: str = None,
        q: str = None,
        order: str = None,
    ):
        snapshot, schema = inputs(ws_name, app_tag)
        if order is not None and order not in ORDERS:
            raise HTTPException(400, f"order must be one of {', '.join(ORDERS)}")
        offset, limit = _clamped(offset, limit, cache.max_page)
        params = dict(
            sort=sort, last=last, offset=offset, limit=limit,
            status=status, query=q, order=order,
        )
        etag = cache.etag(snapshot, schema, **params)
        unchanged = not_modified(request, etag)
        if unchanged is not None:
            return unchanged
        # A query that will not compile is the caller's typo: answer 400 with
        # the compiler's message (it carries the offset), not a 500.
        try:
            payload = cache.page(snapshot, schema, **params)
        except QueryError as e:
            raise HTTPException(400, str(e))
        return json_response(payload, etag=etag, request=request)

    @app.get(f"{base}/experiments-facets")
    def experiment_facets(request: Request, ws_name: str, app_tag: str):
        snapshot, _ = inputs(ws_name, app_tag)
        return json_response(cache.facets(snapshot), request=request)
