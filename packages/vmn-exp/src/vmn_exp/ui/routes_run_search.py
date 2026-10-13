#!/usr/bin/env python3
"""``GET .../workspaces/{ws}/apps/{app}/search?text=&limit=20``: ⌘K "go to
run" over every run of an app (plan 23 S8), answered from the search index
(:mod:`~vmn_exp.ui.search_index`, ranked by :mod:`~vmn_exp.ui.search_rank`).

``{"results": [{verstr, idx, name, status, root, root_name, match}]}``:
``root`` is the run's top-level ancestor (its job), ``match`` the field that
matched (``idx`` for ``@N``). At most *limit* (clamped to 1..50) results;
archived runs only with ``archived=1``. The ETag (index generation, time
bucket and parameters) is known before any search, so a repeat is a ``304``.
"""
from fastapi import Request
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.responses import memoized_json_response

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
ENCODED_BODIES = 64


def register(app, api_prefix, snapshot_of, cache):
    """*snapshot_of(ws_name, app_tag)* -> the app's index snapshot (404 for
    no such app); *cache* a :class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache`."""
    bodies = LRU(ENCODED_BODIES)

    @app.get(f"{api_prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/search",
             dependencies=[require(VIEWER)])
    def search_runs(request: Request, ws_name: str, app_tag: str, text: str = "",
                    limit: int = DEFAULT_LIMIT, archived: bool = False):
        snapshot = snapshot_of(ws_name, app_tag)
        params = dict(text=text, limit=max(1, min(int(limit), MAX_LIMIT)), archived=archived)
        etag = cache.etag(snapshot, None, route="search", **params)
        return memoized_json_response(
            request, etag, lambda: cache.search(snapshot, **params), bodies)
