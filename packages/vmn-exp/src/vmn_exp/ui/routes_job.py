#!/usr/bin/env python3
"""A job's routes (plan 23 S3): ``.../experiments/{verstr}/summary`` (the
rollup, the job's row fields, its top 10 and timeline) and
``.../experiments/{verstr}/failures`` (failure clusters). With
``?split=tags.<k>|params.<k>`` (default: the app's ``experiment.ui.split_by``)
the summary adds its counts and durations per value (plan 28 P3). A run
without children is a 404. Both answer from the app's index snapshot through
:class:`~vmn_exp.ui.job_views.JobViews`, with an ETag known before
anything is built (index generation, time bucket, minute, parameters), so
a poll answers ``304`` for the cost of a hash; encoded bodies are kept per
ETag.
"""
from fastapi import HTTPException, Request
from vmn_exp.ui.auth.authz import require
from vmn_exp.ui.auth.principal import VIEWER
from vmn_exp.ui.job_split import check_split
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.responses import memoized_json_response

ENCODED_BODIES = 64
MAX_CLUSTERS = 100


def _split(field, default):
    """The ``split`` asked for (400 unless a tag or a param), else *default()*."""
    if field is None:
        return default()
    try:
        return check_split(field)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def register(app, prefix, leaderboard_inputs, views, segment, default_split):
    """*leaderboard_inputs(ws_name, app_tag)* -> ``(snapshot, effective
    schema)``; *views* a :class:`~vmn_exp.ui.job_views.JobViews`;
    *segment(verstr)* raises a 400 for an unsafe verstr;
    *default_split(ws_name, app_tag)* the app's default ``split`` or None."""
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
    def job_summary(request: Request, ws_name: str, app_tag: str, verstr: str,
                    split: str = None):
        split = _split(split, lambda: default_split(ws_name, app_tag))
        return answer(request, ws_name, app_tag, verstr, views.summary, "summary",
                      split=split)

    @app.get(f"{base}/failures", dependencies=[require(VIEWER)])
    def job_failures(request: Request, ws_name: str, app_tag: str, verstr: str,
                     limit: int = 20):
        limit = max(1, min(limit, MAX_CLUSTERS))
        return answer(request, ws_name, app_tag, verstr, views.failures,
                      "failures", limit=limit)
