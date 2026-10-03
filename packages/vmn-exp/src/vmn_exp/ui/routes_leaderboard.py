#!/usr/bin/env python3
"""The leaderboard routes: ``.../experiments`` pages, ``.../experiments-columns``
(whole-set chart data), ``.../experiments-importance`` (which params drive a
metric) and ``.../experiments-facets``.

Both answer from the app's current index snapshot through a
:class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache`, so a poll costs
a page slice, and its encoded body is kept per ETag, so identical requests
from many clients render and compress it once. The list's ``ETag`` is known
before any row is touched (index generation, parameters, and the time bucket
while runs are live): a client
repeating it gets an empty ``304`` without the payload ever being built.
Archived rows are left out of all of them unless the request passes
``archived=1``.
"""
from functools import partial

from fastapi import HTTPException, Request

from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.core.query import QueryError
from vmn_exp.ui.leaderboard_comments import joined, page_by_comments, reads_comments
from vmn_exp.ui.http_params import clamp_page, key_list
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.experiments import ORDERS
from vmn_exp.ui.responses import json_response, memoized_json_response

# Encoded bodies kept per ETag (pages, chart columns): a few generations' worth.
ENCODED_BODIES = 64


def register(app, api_prefix, inputs, cache, comments_of=None):
    """*inputs(ws_name, app_tag)* -> ``(snapshot, metrics schema)``, raising
    the route's HTTP errors for a bad workspace or app; *comments_of(ws_name,
    app_tag)* -> ``({verstr: {total, unresolved}}, generation)``; without it
    rows carry no comment counts."""
    comments_of = comments_of or (lambda ws_name, app_tag: ({}, 0))
    base = f"{api_prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}"
    bodies = LRU(ENCODED_BODIES)

    @app.get(f"{base}/experiments", dependencies=[require(VIEWER)])
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
        counts, generation = comments_of(ws_name, app_tag)
        try:
            by_comments = reads_comments(q)
        except QueryError as e:
            raise HTTPException(400, str(e))
        compute = (partial(page_by_comments, cache, counts=counts) if by_comments
                   else cache.page)
        return _answer(request, lambda *a, **p: joined(compute(*a, **p), counts),
                       snapshot, schema, params, comments=generation)

    @app.get(f"{base}/experiments-columns", dependencies=[require(VIEWER)])
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

    @app.get(f"{base}/experiments-importance", dependencies=[require(VIEWER)])
    def experiment_importance(
        request: Request,
        ws_name: str,
        app_tag: str,
        metric: str,
        q: str = None,
        status: str = None,
        archived: bool = False,
    ):
        snapshot, schema = inputs(ws_name, app_tag)
        params = dict(metric=metric, status=status, query=q, archived=archived)
        return _answer(request, cache.importance, snapshot, schema, params, route="importance")

    @app.get(f"{base}/experiments-facets", dependencies=[require(VIEWER)])
    def experiment_facets(
        request: Request, ws_name: str, app_tag: str, archived: bool = False
    ):
        snapshot, _ = inputs(ws_name, app_tag)
        return json_response(cache.facets(snapshot, archived=archived), request=request)

    def _answer(request, compute, snapshot, schema, params, **tag_extra):
        """A ``304`` when the ETag matches, else *compute*'s payload."""
        etag = cache.etag(snapshot, schema, **params, **tag_extra)
        # A query that will not compile (or an unknown column) is the caller's
        # typo: answer 400 with the message (a query's carries the offset).
        try:
            return memoized_json_response(
                request, etag, lambda: compute(snapshot, schema, **params), bodies
            )
        except (QueryError, ValueError) as e:
            raise HTTPException(400, str(e))


def _check_order(order):
    if order is not None and order not in ORDERS:
        raise HTTPException(400, f"order must be one of {', '.join(ORDERS)}")
