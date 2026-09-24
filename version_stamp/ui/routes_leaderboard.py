#!/usr/bin/env python3
"""The leaderboard routes: ``.../experiments`` pages, ``.../experiments-columns``
(whole-set chart data) and ``.../experiments-facets``.

Both answer from the app's current index snapshot through a
:class:`~version_stamp.ui.leaderboard_cache.LeaderboardCache`, so a poll costs
a page slice. The list's ``ETag`` is known before any row is touched (index
generation, parameters, and the time bucket while runs are live): a client
repeating it gets an empty ``304`` without the payload ever being built.
Archived rows are left out of all three unless the request passes
``archived=1``.
"""
from fastapi import HTTPException, Request

from version_stamp.core.experiment_query import QueryError
from version_stamp.ui.http_params import clamp_page, key_list
from version_stamp.ui.readers.experiments import ORDERS
from version_stamp.ui.responses import json_response, not_modified


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
        archived: bool = False,
    ):
        snapshot, schema = inputs(ws_name, app_tag)
        _check_order(order)
        offset, limit = clamp_page(offset, limit, cache.max_page)
        params = dict(
            sort=sort, last=last, offset=offset, limit=limit,
            status=status, query=q, order=order, archived=archived,
        )
        return _answer(request, cache.page, snapshot, schema, params)

    @app.get(f"{base}/experiments-columns")
    def experiment_columns(
        request: Request,
        ws_name: str,
        app_tag: str,
        keys: str = None,
        q: str = None,
        status: str = None,
        sort: str = None,
        order: str = None,
        limit: int = None,
        archived: bool = False,
    ):
        snapshot, schema = inputs(ws_name, app_tag)
        _check_order(order)
        params = dict(
            keys=tuple(key_list(keys) or ()), limit=limit,
            sort=sort, status=status, query=q, order=order, archived=archived,
        )
        return _answer(request, cache.columns, snapshot, schema, params, route="columns")

    @app.get(f"{base}/experiments-facets")
    def experiment_facets(
        request: Request, ws_name: str, app_tag: str, archived: bool = False
    ):
        snapshot, _ = inputs(ws_name, app_tag)
        return json_response(cache.facets(snapshot, archived=archived), request=request)

    def _answer(request, compute, snapshot, schema, params, **tag_extra):
        """A ``304`` when the ETag matches, else *compute*'s payload."""
        etag = cache.etag(snapshot, schema, **params, **tag_extra)
        unchanged = not_modified(request, etag)
        if unchanged is not None:
            return unchanged
        # A query that will not compile (or an unknown column) is the caller's
        # typo: answer 400 with the message (a query's carries the offset).
        try:
            payload = compute(snapshot, schema, **params)
        except (QueryError, ValueError) as e:
            raise HTTPException(400, str(e))
        return json_response(payload, etag=etag, request=request)


def _check_order(order):
    if order is not None and order not in ORDERS:
        raise HTTPException(400, f"order must be one of {', '.join(ORDERS)}")
