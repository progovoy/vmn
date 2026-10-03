#!/usr/bin/env python3
"""``GET /api/v1/search?q=&limit=``: the query language over every app of
every workspace the caller may view (plan 11 §4.4).

Without a database the rows are filtered in Python, app by app; with a
Postgres ``search_dsn`` they are synced into ``vmn_search_rows`` and the
query runs as SQL (:mod:`vmn_exp.ui.search_pg`). Archived runs are left
out unless ``archived=1``. One more row than *limit* is looked for, so
``truncated`` says whether more matched.
"""
from fastapi import HTTPException, Request

from vmn_exp.core.log import filter_archived
from vmn_exp.core.query import QueryError
from vmn_exp.core.tree import annotate_rows
from vmn_exp.ui.auth.authz import allowed, require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.readers import experiments as exp_reader

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


def _rows(snapshot):
    return annotate_rows(snapshot.rows, snapshot.run_states, snapshot.run_state_observed_at)


def _viewable(request, names):
    state = request.app.state
    if not getattr(state, "auth_enabled", False):
        return names
    principal = request.state.principal
    mappings = getattr(state, "role_mappings", ())
    return [name for name in names if allowed(principal, name, VIEWER, mappings)]


def _python_search(scopes, text, limit, archived):
    found = []
    for workspace, app, snapshot in scopes:
        rows = filter_archived(_rows(snapshot), archived)
        matched = exp_reader.apply_filters(rows, query=text, snapshot=snapshot)
        found.extend((workspace, app, row) for row in matched[: limit - len(found)])
        if len(found) >= limit:
            break
    return found


def _sql_search(sql, scopes, names, text, limit, archived):
    for workspace, app, snapshot in scopes:
        sql.sync(workspace, app, snapshot.generation, lambda s=snapshot: _rows(s))
    return sql.search(names, text, limit, archived)


def register(app, api_prefix, scopes_of, sql=None):
    """*scopes_of(names)* yields ``(workspace, app, snapshot)`` of those
    workspaces in order; *sql* is a :class:`~vmn_exp.ui.search_pg.PgRowSearch`."""

    @app.get(f"{api_prefix}/search", dependencies=[require(VIEWER)])
    def search(request: Request, q: str = "", limit: int = DEFAULT_LIMIT, archived: bool = False):
        limit = max(1, min(limit, MAX_LIMIT))
        names = sorted(_viewable(request, [ws.name for ws in app.state.manager.list()]))
        try:
            if sql is None:
                found = _python_search(scopes_of(names), q, limit + 1, archived)
            else:
                found = _sql_search(sql, scopes_of(names), names, q, limit + 1, archived)
        except QueryError as exc:
            raise HTTPException(400, str(exc))
        results = [
            {"workspace": ws, "app": name, "verstr": row["verstr"], "row": row}
            for ws, name, row in found[:limit]
        ]
        return {"results": results, "truncated": len(found) > limit}
