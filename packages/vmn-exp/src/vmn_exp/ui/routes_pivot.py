#!/usr/bin/env python3
"""``GET .../experiments-pivot`` (plan 28 N2): the app's runs (or, with
``scope=<verstr>``, an outer run's subtree) crossed by two group fields,
``rows=`` x ``cols=``, each cell a count (``cell=count``, the default), the
share of its runs matching a query (``cell=share&match=<query>``) or an
aggregate of a metric (``cell=agg&metric=<m>&agg=mean|best|median|min|max``,
default the app's group aggregate); ``q``, ``status`` and ``archived``
filter the runs as on the board. See :mod:`~vmn_exp.ui.pivot` for the body
and :mod:`~vmn_exp.ui.pivot_cache` for what is kept. The ETag is known
before anything is built; encoded bodies are kept per ETag.
"""
from fastapi import HTTPException, Request
from vmn_exp.core.query import QueryError
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.leaderboard_scope import UnknownScope
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.pivot import pivot_spec
from vmn_exp.ui.pivot_cache import PivotCache
from vmn_exp.ui.responses import memoized_json_response
from vmn_exp.ui.security import safe_segment

ENCODED_BODIES = 32


def register(app, api_prefix, inputs, cache, aggregate_of):
    """*inputs(ws_name, app_tag)* -> ``(snapshot, metrics schema)``; *cache*
    the app's :class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache`;
    *aggregate_of(ws_name, app_tag)* the app's default group aggregate."""
    pivots = PivotCache(cache)
    bodies = LRU(ENCODED_BODIES)
    route = f"{api_prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments-pivot"

    @app.get(route, dependencies=[require(VIEWER)])
    def experiment_pivot(
        request: Request, ws_name: str, app_tag: str, rows: str, cols: str,
        cell: str = "count", match: str = None, metric: str = None, agg: str = None,
        q: str = None, status: str = None, archived: bool = False, scope: str = None,
    ):
        if not safe_segment(scope):
            raise HTTPException(400, f"Invalid scope '{scope}'")
        snapshot, schema = inputs(ws_name, app_tag)
        try:
            spec = pivot_spec(rows, cols, cell, match, metric,
                              agg or aggregate_of(ws_name, app_tag), status, q, archived, scope)
            etag = cache.etag(snapshot, schema, route="pivot", spec=spec)
            return memoized_json_response(
                request, etag, lambda: pivots.pivot(snapshot, schema, spec), bodies)
        except UnknownScope as e:
            raise HTTPException(404, str(e))
        except (QueryError, ValueError) as e:
            raise HTTPException(400, str(e))
