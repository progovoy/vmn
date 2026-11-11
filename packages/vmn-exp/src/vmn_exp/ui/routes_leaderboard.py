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
summary, sortable by ``job:*`` (plan 23 S2, :mod:`~vmn_exp.ui.leaderboard_jobs`),
a paged answer (and a tree page) carrying ``main``, the metric and goal those
summaries are of (plan 32 F10);
``match_subtree=1`` matches ``q`` over their subtrees instead (plan 23 S8b,
:mod:`~vmn_exp.ui.leaderboard_subtree_match`; flat pages only).
``top=jobs``/``top=singles`` those with and without children (plan 23 S7).
``top_q`` (with ``top``) keeps the top-level runs passing it by their own
fields, beside ``q``, flat or grouped: the Live/Review presets (plan 28 §4.5).
A flat page carries ``next_cursor``; ``cursor=`` asks for the page after it
(keyset paging, plan 23 S6, :mod:`~vmn_exp.ui.leaderboard_cursor`).
Grouped with ``top``, each group sums its jobs' rollups and pools their units
(plan 34 §1; ``collapse_all=1``: the headers alone), and the page names the
aggregate (``job_agg``) even when no header has a value; every group carries
the ``clause`` selecting it (:mod:`~vmn_exp.ui.leaderboard_group_clause`).
A ``q`` (or ``top_q``) with ``ago()`` is pinned to the minute first (plan 28 P1,
:func:`~vmn_exp.ui.attention.pinned`), so its ETag and orders follow the
clock; a Jobs view page's ``job`` carries the app's attention counts.
With ``top``, each row's ``job`` carries ``rolled``, the aggregate
``job_agg``/``job_agg_by``/``job_agg_value``/``job_agg_metric``/
``job_agg_nested`` (plan 36 §2) name over the
app's ``experiment.ui.job_aggregate`` (plan 31 §2,
:mod:`~vmn_exp.ui.job_aggregate`), sortable by ``job:value``; a bad value,
or one without ``top``, is a 400.
``children_of=<verstr>`` pages that run's direct children for the tree
(plan 28 N6, :mod:`~vmn_exp.ui.leaderboard_children`): each with children
carrying its ``job`` (attention over its own subtree, the app's split),
every row an ``open`` hint, the page the app's ``tree_columns``; with
``match_subtree=1`` the status and ``q`` keep the children whose subtree holds
a passing run, each carrying ``matched`` (:mod:`~vmn_exp.ui.leaderboard_tree_match`).
A flat or grouped page matching nothing carries ``hints`` ("did you mean
tags.kind?", :mod:`~vmn_exp.core.query_hints`); the web page's own URL params
(``view``, ``kind``, ``tab``, ``sel``) are a 400 (plan 31 §4.2).
"""
from functools import partial

from fastapi import Depends, HTTPException, Request
from vmn_exp.core.app_settings import tree_columns_of
from vmn_exp.core.query import QueryError
from vmn_exp.ui.attention import pinned, queries_of
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.http_params import clamp_page, key_list
from vmn_exp.ui.indexing import indexed_response
from vmn_exp.ui.job_aggregate import job_agg_of
from vmn_exp.ui.job_rollup_cache import minute
from vmn_exp.ui.leaderboard_comments import (
    groups_by_comments,
    joined,
    joined_groups,
    page_by_comments,
    reads_comments,
)
from vmn_exp.ui.leaderboard_group_fields import DEFAULT_AGGREGATE, UnknownGroup
from vmn_exp.ui.leaderboard_params import (
    GROUPED,
    TREE,
    GroupParams,
    JobAggParams,
    PageParams,
    TreeParams,
    resolve_mode,
)
from vmn_exp.ui.leaderboard_scope import UnknownScope, top_filter
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.experiments import ORDERS, split_by_of
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
        page: PageParams = Depends(),
        grouping: GroupParams = Depends(),
        tree: TreeParams = Depends(),
        job_agg: JobAggParams = Depends(),
    ):
        snapshot, schema = inputs(ws_name, app_tag)
        _check_order(page.order)
        top, q, top_q = _top(page.top), _pinned(page.q), _pinned(page.top_q)
        try:
            by_comments = reads_comments(q)
        except QueryError as e:
            raise HTTPException(400, str(e))
        mode = resolve_mode(page, grouping, tree, job_agg, top=top, by_comments=by_comments)
        aggregate = _job_agg(ws_name, app_tag, job_agg) if mode.jobs else {}
        live = mode.jobs or mode.shape == TREE
        attention = queries_of(attention_of(ws_name, app_tag)) if live else ()
        offset, limit = clamp_page(page.offset, page.limit, cache.max_page)
        params = dict(offset=offset, limit=limit, sort=page.sort, status=page.status, query=q,
                      order=page.order, archived=page.archived, scope=_scope(page.scope),
                      top=top, top_query=top_q, **aggregate)
        # A Jobs view's summaries (throughput, ETA) follow the minute; the
        # etag carries the live bucket already.
        clock = dict(minute=minute()) if live else {}
        counts, generation = comments_of(ws_name, app_tag)
        if mode.shape == TREE:
            _scope(tree.children_of)
            return _tree_page(request, ws_name, app_tag, snapshot, schema, counts,
                              dict(params, last=page.last, cursor=page.cursor,
                                   children_of=tree.children_of,
                                   match_subtree=page.match_subtree),
                              attention, comments=generation, **clock)
        if mode.shape == GROUPED:
            return _grouped_page(request, ws_name, app_tag, snapshot, schema, counts, params,
                                 grouping, top, by_comments, comments=generation, **clock)
        if by_comments:
            compute = partial(page_by_comments, cache, counts=counts)
        else:
            compute = partial(cache.page, match_subtree=page.match_subtree, attention=attention)
        answer = _with_hints(_with_main(lambda *a, **p: joined(compute(*a, **p), counts), top))
        return _answer(request, answer, snapshot, schema,
                       dict(params, last=page.last, cursor=page.cursor), comments=generation,
                       match_subtree=page.match_subtree and not by_comments, attention=attention,
                       **clock)

    def _grouped_page(request, ws_name, app_tag, snapshot, schema, counts, params, grouping,
                      top, by_comments, **tag_extra):
        """A grouped page: *params*' groups by ``grouping.group``."""
        rows_per_group = grouping.rows_per_group
        if grouping.group_key is None:
            params["limit"], rows_per_group = grouped_page(params["limit"], rows_per_group)
            # One row per group (plan 34 §1): the headers alone.
            rows_per_group = 0 if grouping.collapse_all else rows_per_group
        params.update(agg=grouping.agg or aggregate_of(ws_name, app_tag),
                      rows_per_group=rows_per_group, group_key=grouping.group_key)
        compute = (partial(groups_by_comments, cache, counts=counts) if by_comments
                   else cache.groups)
        group = grouping.group
        return _answer(request, _with_hints(_with_main(lambda s, sc, **p: joined_groups(
            compute(s, sc, group, **p), counts), top)),
                       snapshot, schema, params, group=group, **tag_extra)

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
        top: str = None,
        top_q: str = None,
        match_subtree: bool = False,
    ):
        snapshot, schema = inputs(ws_name, app_tag)
        _check_order(order)
        top = _top(top)
        if (top_q or match_subtree) and not top:
            raise HTTPException(400, "top_q and match_subtree need top=1")
        params = dict(
            keys=tuple(key_list(keys) or ()), limit=limit,
            sort=sort, status=status, query=_pinned(q), order=order, archived=archived,
            scope=_scope(scope), top=top, top_query=_pinned(top_q), match_subtree=match_subtree,
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
            return indexed_response(
                request, etag, snapshot, lambda: cache.facets_payload(snapshot, **where), bodies)
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

        return _answer(request, _with_main(compute), snapshot, schema, params, attention=attention,
                       split=split, tree_columns=columns, **tag_extra)

    def _with_main(compute, jobs=True):
        """*compute* whose page (a dict) carries ``main``, the metric and
        goal of its ``job`` summaries, when it is of *jobs* (plan 32 F10)."""
        if not jobs:
            return compute

        def answer(snapshot, schema, **params):
            body = compute(snapshot, schema, **params)
            if not isinstance(body, dict):
                return body
            return dict(body, main=cache.jobs.main(snapshot, schema))
        return answer

    def _with_hints(compute):
        """*compute* whose page (a dict) matching no row carries ``hints``
        when its queries name a row field a tag or param holds the value of
        (plan 31 §4.2)."""
        def answer(snapshot, schema, **params):
            body = compute(snapshot, schema, **params)
            if not isinstance(body, dict) or body.get("total", body.get("total_rows")) != 0:
                return body
            found = cache.query_hints(snapshot, (params.get("query"), params.get("top_query")),
                                      params.get("archived"))
            return dict(body, hints=found) if found else body
        return answer

    def _job_agg(ws_name, app_tag, job_agg):
        """``{job_agg: JobAgg}`` of a Jobs view request (400 for a bad value)."""
        try:
            return {"job_agg": job_agg_of(ui_of(ws_name, app_tag), **job_agg.given())}
        except ValueError as e:
            raise HTTPException(400, str(e))

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
            return indexed_response(
                request, etag, snapshot, lambda: compute(snapshot, schema, **params), bodies
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


def _check_order(order):
    if order is not None and order not in ORDERS:
        raise HTTPException(400, f"order must be one of {', '.join(ORDERS)}")
