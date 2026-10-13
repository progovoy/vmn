#!/usr/bin/env python3
"""A job's routes (plan 23 S3): ``.../experiments/{verstr}/summary`` (the
rollup, the job's row fields, its top 10 and timeline) and
``.../experiments/{verstr}/failures`` (failure clusters). A run without
children is a 404. Both answer from the app's index snapshot through
:class:`~vmn_exp.ui.job_views.JobViews`, with an ETag known before
anything is built (index generation, time bucket, minute, parameters), so
a poll answers ``304`` for the cost of a hash; encoded bodies are kept per
ETag.
"""
from fastapi import HTTPException, Request
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.responses import memoized_json_response

ENCODED_BODIES = 64
MAX_CLUSTERS = 100


def register(app, prefix, leaderboard_inputs, views, segment):
    """*leaderboard_inputs(ws_name, app_tag)* -> ``(snapshot, effective
    schema)``; *views* a :class:`~vmn_exp.ui.job_views.JobViews`;
    *segment(verstr)* raises a 400 for an unsafe verstr."""
    base = f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/experiments/{{verstr}}"
    bodies = LRU(ENCODED_BODIES)

    def answer(request, ws_name, app_tag, verstr, compute, route, **params):
        segment(verstr)
        snapshot, schema = leaderboard_inputs(ws_name, app_tag)
        if not views.is_job(snapshot, verstr):
            raise HTTPException(404, f"{verstr} is not a job (it has no runs under it)")
        etag = views.etag(snapshot, schema, verstr, route=route, **params)
        return memoized_json_response(
            request, etag, lambda: compute(snapshot, schema, verstr, **params), bodies)

    @app.get(f"{base}/summary", dependencies=[require(VIEWER)])
    def job_summary(request: Request, ws_name: str, app_tag: str, verstr: str):
        return answer(request, ws_name, app_tag, verstr, views.summary, "summary")

    @app.get(f"{base}/failures", dependencies=[require(VIEWER)])
    def job_failures(request: Request, ws_name: str, app_tag: str, verstr: str,
                     limit: int = 20):
        limit = max(1, min(limit, MAX_CLUSTERS))
        return answer(request, ws_name, app_tag, verstr, views.failures,
                      "failures", limit=limit)
