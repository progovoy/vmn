#!/usr/bin/env python3
"""The dashboard shell's routes: ``.../workspaces/{ws}/git`` (branch, HEAD,
dirty) and ``.../apps/{app}/experiments-status`` (the status rollup)."""
from fastapi import Request

import vmn_exp.core.status as experiment_status
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.git_context import git_context
from vmn_exp.ui.memo import LRU, TTLCache
from vmn_exp.ui.responses import json_response
from vmn_exp.ui.status_summary import status_summary

GIT_TTL_SEC = 5
STATUS_BODIES = 64


def register(app, prefix, git_workspace, leaderboard_inputs, leaderboards):
    """Add the routes; *git_workspace(ws_name)* raises the route's 400/404,
    *leaderboard_inputs(ws_name, app_tag)* -> ``(snapshot, schema)``. Returns
    ``forget(ws_name)``, which drops a removed workspace's git context."""
    contexts = TTLCache(GIT_TTL_SEC)
    summaries = LRU(STATUS_BODIES)

    @app.get(f"{prefix}/workspaces/{{ws_name}}/git", dependencies=[require(VIEWER)])
    def workspace_git(ws_name: str):  # sync: git runs in the threadpool
        path = git_workspace(ws_name).path
        return contexts.get(ws_name, lambda: git_context(path))

    @app.get(
        f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments-status",
        dependencies=[require(VIEWER)],
    )
    def experiments_status(request: Request, ws_name: str, app_tag: str):
        snapshot, schema = leaderboard_inputs(ws_name, app_tag)
        now = experiment_status._now()
        # failed_recent ages with the clock even while nothing is live (when
        # the etag has no time bucket): the window is accurate to an hour.
        hour = int(now.timestamp() // 3600)
        etag = leaderboards.etag(snapshot, schema, kind="status", hour=hour)
        payload = summaries.get(
            etag, lambda: status_summary(leaderboards.ordered(snapshot, schema), now)
        )
        return json_response(payload, etag=etag, request=request)

    return contexts.pop
