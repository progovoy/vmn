#!/usr/bin/env python3
"""The dashboard shell's routes: ``.../workspaces/{ws}/git`` (branch, HEAD,
dirty), ``.../apps/{app}/experiments-status`` (an app's status rollup) and
``.../workspaces/{ws}/apps-status`` (every app's, in one request); while an
app's index still loads, its status carries ``indexing`` ``{loaded, total}``,
and a background-refreshed one its refresher's health (``refresher``: alive,
failing, failures, since_refresh_sec, refreshing_sec, last_error), so the
dashboard (and a load balancer) see an index that stopped refreshing."""
import hashlib
import json

from fastapi import Request

import vmn_exp.core.status as experiment_status
from vmn_exp.ui.api_errors import CodedError
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.git_context import git_context
from vmn_exp.ui.memo import LRU, TTLCache
from vmn_exp.ui.responses import json_response
from vmn_exp.ui.status_summary import status_summary

GIT_TTL_SEC = 5
STATUS_BODIES = 256


def register(app, prefix, git_workspace, status_snapshot, app_tags, leaderboards,
             refresher_health):
    """Add the routes; *git_workspace(ws_name)* raises the route's 400/404,
    *status_snapshot(ws_name, app_tag)* -> the app's snapshot (raising its
    404 when there is no such app), *app_tags(ws_name)* -> the workspace's
    apps in tag form, *refresher_health(ws_name, app_tag)* -> its index's
    refresh health or None (after the snapshot was asked for). Returns ``forget(ws_name)``, which drops a removed
    workspace's git context."""
    contexts = TTLCache(GIT_TTL_SEC)
    summaries = LRU(STATUS_BODIES)

    def summary(ws_name, app_tag, now):
        """``(summary, etag)`` of an app, memoized per etag."""
        snapshot = status_snapshot(ws_name, app_tag)
        health = refresher_health(ws_name, app_tag)
        # failed_recent ages with the clock even while nothing is live (when
        # the etag has no time bucket): the window is accurate to an hour.
        hour = int(now.timestamp() // 3600)
        etag = leaderboards.etag(snapshot, {}, kind="status", hour=hour,
                                 refresher=_health_key(health))
        payload = summaries.get(etag, lambda: _with_refresher(_with_indexing(
            status_summary(leaderboards.rows(snapshot), now), snapshot), health))
        return payload, etag

    @app.get(f"{prefix}/workspaces/{{ws_name}}/git", dependencies=[require(VIEWER)])
    def workspace_git(ws_name: str):  # sync: git runs in the threadpool
        path = git_workspace(ws_name).path
        return contexts.get(ws_name, lambda: git_context(path))

    @app.get(
        f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments-status",
        dependencies=[require(VIEWER)],
    )
    def experiments_status(request: Request, ws_name: str, app_tag: str):
        payload, etag = summary(ws_name, app_tag, experiment_status._now())
        return json_response(payload, etag=etag, request=request)

    @app.get(f"{prefix}/workspaces/{{ws_name}}/apps-status", dependencies=[require(VIEWER)])
    def apps_status(request: Request, ws_name: str):
        now = experiment_status._now()
        answers = {}
        for tag in app_tags(ws_name):
            try:
                answers[tag] = summary(ws_name, tag, now)
            except CodedError:  # gone since the app list was read
                continue
        payload = {tag: body for tag, (body, _) in answers.items()}
        etags = json.dumps([[tag, etag] for tag, (_, etag) in answers.items()])
        etag = hashlib.blake2b(etags.encode(), digest_size=16).hexdigest()
        return json_response(payload, etag=etag, request=request)

    return contexts.pop


def _with_indexing(payload, snapshot):
    """*payload* with ``indexing`` ``{loaded, total}`` while *snapshot*'s
    index is still loading chunk by chunk."""
    if snapshot.loading is None:
        return payload
    loaded, total = snapshot.loading
    return dict(payload, indexing={"loaded": loaded, "total": total})


def _health_key(health):
    """What of *health* changes the status body: its state, and its ages by
    the minute (a healthy index's stay 0, so its etag holds)."""
    if health is None:
        return None
    minutes = [None if health[k] is None else int(health[k] // 60)
               for k in ("since_refresh_sec", "refreshing_sec")]
    return [health["alive"], health["failures"], health["last_error"], *minutes]


def _with_refresher(payload, health):
    return payload if health is None else dict(payload, refresher=health)
