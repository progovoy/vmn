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
``archived=1``. With ``group=`` the list answers groups instead of a page
(plan 22 K1, :mod:`~vmn_exp.ui.leaderboard_groups`). ``scope=<verstr>``
narrows each of them to that run's subtree (without it; an unknown run is a
404), and ``top=1`` the list to the top-level runs, each with its ``job``
summary, sortable by ``job:*`` (plan 23 S2, :mod:`~vmn_exp.ui.leaderboard_jobs`);
``match_subtree=1`` matches ``q`` over their subtrees instead (plan 23 S8b,
:mod:`~vmn_exp.ui.leaderboard_subtree_match`; flat pages only).
``top=jobs``/``top=singles`` those with and without children (plan 23 S7).
``top_q`` (with ``top``) keeps the top-level runs passing it by their own
fields, beside ``q``, flat or grouped: the Live/Review presets (plan 28 §4.5).
A flat page carries ``next_cursor``; ``cursor=`` asks for the page after it
(keyset paging, plan 23 S6, :mod:`~vmn_exp.ui.leaderboard_cursor`).
Grouped with ``top``, each group sums its jobs' rollups; every group carries
the ``clause`` selecting it (:mod:`~vmn_exp.ui.leaderboard_group_clause`).
A ``q`` (or ``top_q``) with ``ago()`` is pinned to the minute first (plan 28 P1,
:func:`~vmn_exp.ui.attention.pinned`), so its ETag and orders follow the
clock; a Jobs view page's ``job`` carries the app's attention counts.
``children_of=<verstr>`` pages that run's direct children for the tree
(plan 28 N6, :mod:`~vmn_exp.ui.leaderboard_children`): each with children
carrying its ``job`` (attention over its own subtree, the app's split),
every row an ``open`` hint, the page the app's ``tree_columns``.
"""
from functools import partial

from fastapi import HTTPException, Request
from vmn_exp.core.app_settings import tree_columns_of
from vmn_exp.core.query import QueryError
from vmn_exp.ui.attention import pinned, queries_of
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.http_params import clamp_page, key_list
from vmn_exp.ui.job_rollup_cache import minute
from vmn_exp.ui.leaderboard_comments import (
    groups_by_comments,
    joined,
    joined_groups,
    page_by_comments,
    reads_comments,
)
from vmn_exp.ui.leaderboard_group_fields import DEFAULT_AGGREGATE, UnknownGroup
from vmn_exp.ui.leaderboard_scope import UnknownScope, top_filter
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.experiments import ORDERS, split_by_of
from vmn_exp.ui.responses import memoized_json_response
from vmn_exp.ui.security import safe_segment

# Encoded bodies kept per ETag (pages, chart columns): a few generations' worth.
ENCODED_BODIES = 64
# A grouped page's size (plan 22 F5): groups, rows per group, rows in all.
MAX_GROUPS = 50
MAX_ROWS_PER_GROUP = 100
MAX_GROUPED_ROWS = 5000


def register(app, api_prefix, inputs, cache, comments_of=None, aggregate_of=None,
             attention_of=None, ui_of=None):
    """*inputs(ws_name, app_tag)* -> ``(snapshot, metrics schema)``, raising
    the route's HTTP errors for a bad workspace or app; *comments_of(ws_name,
    app_tag)* -> ``({verstr: {total, unresolved}}, generation)``; without it
    rows carry no comment counts. *aggregate_of(ws_name, app_tag)* -> the
    app's default group aggregate (conf ``experiment.ui.group_aggregate``);
    *attention_of(ws_name, app_tag)* -> its attention entries; *ui_of(ws_name,
    app_tag)* -> its ``experiment.ui`` (a tree page's split and columns)."""
    ui_of = ui_of or (lambda ws_name, app_tag: {})
    comments_of = comments_of or (lambda ws_name, app_tag: ({}, 0))
    aggregate_of = aggregate_of or (lambda ws_name, app_tag: DEFAULT_AGGREGATE)
    attention_of = attention_of or (lambda ws_name, app_tag: [])
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
        group: str = None,
        agg: str = None,
        rows_per_group: int = 10,
        group_key: str = None,
        scope: str = None,
        top: str = None,
        match_subtree: bool = False,
        cursor: str = None,
        children_of: str = None,
        top_q: str = None,
    ):
        snapshot, schema = inputs(ws_name, app_tag)
        _check_order(order)
        top, q, top_q = _top(top), _pinned(q), _pinned(top_q)
        if top_q and not top:
            raise HTTPException(400, "top_q needs top=1")
        tree = children_of is not None
        attention = queries_of(attention_of(ws_name, app_tag)) if top or tree else ()
        offset, limit = clamp_page(offset, limit, cache.max_page)
        params = dict(offset=offset, limit=limit, sort=sort, status=status, query=q,
                      order=order, archived=archived, scope=_scope(scope), top=top,
                      top_query=top_q)
        # A Jobs view's summaries (throughput, ETA) follow the minute; the
        # etag carries the live bucket already.
        clock = dict(minute=minute()) if top or tree else {}
        counts, generation = comments_of(ws_name, app_tag)
        try:
            by_comments = reads_comments(q)
        except QueryError as e:
            raise HTTPException(400, str(e))
        if tree:
            _scope(children_of)
            _check_tree(group, by_comments)
            return _tree_page(request, ws_name, app_tag, snapshot, schema, counts,
                              dict(params, last=last, cursor=cursor, children_of=children_of),
                              attention, comments=generation, **clock)
        if group is not None:
            if last or cursor is not None:
                raise HTTPException(400, "last and cursor cannot be combined with group")
            if group_key is None:
                params["limit"], rows_per_group = grouped_page(limit, rows_per_group)
            params.update(agg=agg or aggregate_of(ws_name, app_tag),
                          rows_per_group=rows_per_group, group_key=group_key)
            compute = (partial(groups_by_comments, cache, counts=counts) if by_comments
                       else cache.groups)
            return _answer(request, lambda s, sc, **p: joined_groups(compute(s, sc, group, **p),
                                                                     counts),
                           snapshot, schema, params, comments=generation, group=group,
                           **clock)
        if by_comments:
            compute = partial(page_by_comments, cache, counts=counts)
        else:
            compute = partial(cache.page, match_subtree=match_subtree, attention=attention)
        return _answer(request, lambda *a, **p: joined(compute(*a, **p), counts), snapshot,
                       schema, dict(params, last=last, cursor=cursor), comments=generation,
                       match_subtree=match_subtree and not by_comments, attention=attention,
                       **clock)

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
        scope: str = None,
    ):
        snapshot, schema = inputs(ws_name, app_tag)
        _check_order(order)
        params = dict(
            keys=tuple(key_list(keys) or ()), limit=limit,
            sort=sort, status=status, query=_pinned(q), order=order, archived=archived,
            scope=_scope(scope),
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
        scope: str = None,
    ):
        snapshot, schema = inputs(ws_name, app_tag)
        params = dict(metric=metric, status=status, query=_pinned(q), archived=archived,
                      scope=_scope(scope))
        return _answer(request, cache.importance, snapshot, schema, params, route="importance")

    @app.get(f"{base}/experiments-facets", dependencies=[require(VIEWER)])
    def experiment_facets(
        request: Request, ws_name: str, app_tag: str, archived: bool = False,
        scope: str = None, q: str = None, status: str = None,
    ):
        snapshot, _ = inputs(ws_name, app_tag)
        where = dict(archived=archived, scope=_scope(scope), query=_pinned(q), status=status)
        etag = cache.etag(snapshot, None, route="facets", **where)
        try:
            return memoized_json_response(
                request, etag, lambda: cache.facets_payload(snapshot, **where), bodies)
        except UnknownScope as e:
            raise HTTPException(404, str(e))
        except QueryError as e:
            raise HTTPException(400, str(e))

    def _tree_page(request, ws_name, app_tag, snapshot, schema, counts, params, attention,
                   **tag_extra):
        """A tree page: *params*' children, with the app's split and ``tree_columns``."""
        ui = ui_of(ws_name, app_tag)
        split, columns = split_by_of(ui), tree_columns_of(ui)

        def compute(*args, **page):
            body = cache.page(*args, **page, attention=attention, split=split)
            return dict(joined(body, counts), tree_columns=columns)

        return _answer(request, compute, snapshot, schema, params, attention=attention,
                       split=split, tree_columns=columns, **tag_extra)

    def _top(top):
        try:
            return top_filter(top)
        except ValueError as e:
            raise HTTPException(400, str(e))

    def _pinned(q):
        try:
            return pinned(q)
        except QueryError as e:
            raise HTTPException(400, str(e))

    def _scope(scope):
        """*scope*, 400 when it is not a verstr (no run having it is the
        cache's :class:`UnknownScope`, a 404)."""
        if not safe_segment(scope):
            raise HTTPException(400, f"Invalid scope '{scope}'")
        return scope

    def _answer(request, compute, snapshot, schema, params, **tag_extra):
        """A ``304`` when the ETag matches, else *compute*'s payload."""
        etag = cache.etag(snapshot, schema, **params, **tag_extra)
        # A query that will not compile (or an unknown column) is the caller's
        # typo: answer 400 with the message (a query's carries the offset).
        try:
            return memoized_json_response(
                request, etag, lambda: compute(snapshot, schema, **params), bodies
            )
        except (UnknownGroup, UnknownScope) as e:
            raise HTTPException(404, str(e))
        except (QueryError, ValueError) as e:
            raise HTTPException(400, str(e))


def grouped_page(limit, rows_per_group):
    """``(groups, rows per group)`` of a grouped page, clamped (not refused)
    to 1..:data:`MAX_GROUPS` groups and 1..:data:`MAX_ROWS_PER_GROUP` rows
    each, the rows per group lowered until the page holds at most
    :data:`MAX_GROUPED_ROWS` rows; no *limit* is the most groups."""
    groups = MAX_GROUPS if limit is None else max(1, min(int(limit), MAX_GROUPS))
    rows = max(1, min(int(rows_per_group), MAX_ROWS_PER_GROUP, MAX_GROUPED_ROWS // groups))
    return groups, rows


def _check_tree(group, by_comments):
    if group is not None:
        raise HTTPException(400, "children_of cannot be combined with group")
    if by_comments:
        raise HTTPException(400, "children_of cannot be combined with a comments query")


def _check_order(order):
    if order is not None and order not in ORDERS:
        raise HTTPException(400, f"order must be one of {', '.join(ORDERS)}")
