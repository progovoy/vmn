#!/usr/bin/env python3
"""The dashboard shell's routes: ``.../workspaces/{ws}/git`` (branch, HEAD,
dirty), ``.../apps/{app}/experiments-status`` (an app's status rollup) and
``.../workspaces/{ws}/apps-status`` (every app's, in one request); while an
app's index still loads, its status carries ``indexing`` ``{loaded, total}``,
and a background-refreshed one how fresh its data is (``freshness``, see
:mod:`vmn_exp.ui.freshness`), so the dashboard (and a load balancer) see an
index that serves old data or stopped refreshing. An app's status also
counts its attention queries (``attention``, plan 28 P1,
:mod:`vmn_exp.ui.attention`), and ``?scope=<verstr>`` answers it all over
that run's subtree (an outer run's page)."""
import hashlib
import json

from fastapi import HTTPException, Request

import vmn_exp.core.status as experiment_status
from vmn_exp.ui.api_errors import CodedError
from vmn_exp.ui.attention import attention_key, attention_payload
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.freshness import freshness_key
from vmn_exp.ui.git_context import git_context
from vmn_exp.ui.leaderboard_scope import UnknownScope
from vmn_exp.ui.memo import LRU, TTLCache
from vmn_exp.ui.responses import json_response
from vmn_exp.ui.security import safe_segment

GIT_TTL_SEC = 5
STATUS_BODIES = 256


def register(app, prefix, git_workspace, status_snapshot, app_tags, leaderboards,
             freshness_of, attention_of=None, schema_of=None):
    """Add the routes; *git_workspace(ws_name)* raises the route's 400/404,
    *status_snapshot(ws_name, app_tag)* -> the app's snapshot (raising its
    404 when there is no such app), *app_tags(ws_name)* -> the workspace's
    apps in tag form, *freshness_of(ws_name, app_tag)* -> its index's
    ``freshness`` or None (after the snapshot was asked for),
    *attention_of(ws_name, app_tag)* -> its attention entries,
    *schema_of(ws_name, app_tag)* -> the board's metrics schema. Returns
    ``forget(ws_name)``, which drops a removed workspace's git context."""
    contexts = TTLCache(GIT_TTL_SEC)
    summaries = LRU(STATUS_BODIES)
    attention_of = attention_of or (lambda ws_name, app_tag: [])

    def summary(ws_name, app_tag, now, scope=None, schema=None, entries=()):
        """``(summary, etag)`` of an app (*scope*'s subtree when given) with
        the *entries*' attention counts, memoized per snapshot."""
        snapshot = status_snapshot(ws_name, app_tag)
        fresh = freshness_of(ws_name, app_tag)
        # failed_recent ages with the clock even while nothing is live (when
        # the etag has no time bucket): the window is accurate to an hour.
        hour = int(now.timestamp() // 3600)
        etag = leaderboards.etag(snapshot, schema if scope else None, kind="status",
                                 hour=hour, scope=scope)
        payload = summaries.get(etag, lambda: _with_indexing(
            leaderboards.status_summary(snapshot, now) if scope is None
            else leaderboards.jobs.status_summary(snapshot, schema, scope), snapshot))
        if entries:
            payload, etag = with_attention(snapshot, schema, scope, entries, payload, etag)
        if fresh is None:
            return payload, etag
        key = json.dumps([etag, freshness_key(fresh, now.timestamp())], default=str)
        return dict(payload, freshness=fresh), _digest(key)

    def with_attention(snapshot, schema, scope, entries, payload, etag):
        """*payload* and *etag* with the *entries*' counts (no ``attention``
        when no part is shown), keyed by their pinned queries (an ``ago()``
        one moves with the minute)."""
        key = leaderboards.etag(snapshot, schema, kind="attention", scope=scope,
                                entries=attention_key(entries))
        parts = summaries.get(key, lambda: attention_payload(
            leaderboards, snapshot, schema, entries, scope))
        return (dict(payload, attention=parts) if parts else payload), _digest(etag + key)

    @app.get(f"{prefix}/workspaces/{{ws_name}}/git", dependencies=[require(VIEWER)])
    def workspace_git(ws_name: str):  # sync: git runs in the threadpool
        path = git_workspace(ws_name).path
        return contexts.get(ws_name, lambda: git_context(path))

    @app.get(
        f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments-status",
        dependencies=[require(VIEWER)],
    )
    def experiments_status(request: Request, ws_name: str, app_tag: str, scope: str = None):
        if not safe_segment(scope):
            raise HTTPException(400, f"Invalid scope '{scope}'")
        entries = attention_of(ws_name, app_tag)
        schema = schema_of(ws_name, app_tag) if entries or scope else None
        try:
            payload, etag = summary(ws_name, app_tag, experiment_status._now(), scope, schema,
                                    entries)
        except UnknownScope as e:
            raise HTTPException(404, str(e))
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
        return json_response(payload, etag=_digest(etags), request=request)

    return contexts.pop


def _with_indexing(payload, snapshot):
    """*payload* with ``indexing`` ``{loaded, total}`` while *snapshot*'s
    index is still loading chunk by chunk."""
    if snapshot.loading is None:
        return payload
    loaded, total = snapshot.loading
    return dict(payload, indexing={"loaded": loaded, "total": total})


def _digest(text):
    return hashlib.blake2b(text.encode(), digest_size=16).hexdigest()
