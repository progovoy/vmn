#!/usr/bin/env python3
"""``POST .../apps/{app}/series`` — many runs' metric series in one request.

A comparison chart needs the same few metrics from dozens of runs; one detail
request per run would carry each run's log tail, artifacts and tree status
along. The body names the runs::

    {"verstrs": ["1.0.0-dev.a", ...], "keys": ["loss"] | null, "max_points": 2000}

and the answer is ``{"series": {verstr: {metric: [points]}}, "series_total":
{verstr: {metric: n}}, "missing": [verstr, ...]}`` with points shaped like the
detail endpoint's. It is a read, so a read-only server serves it too; as a
POST it still passes the JSON Content-Type / same-origin guard.
"""
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException, Request

from version_stamp.ui.readers import experiment_detail as detail_reader
from version_stamp.ui.readers import series as series_reader
from version_stamp.ui.responses import json_response
from version_stamp.ui.security import safe_segment

MAX_RUNS = 200
WORKERS = 8
_POOL = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="vmn-ui-series")


def _string_list(value, what, limit=None):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise HTTPException(400, f"{what} must be a list of strings")
    if limit is not None and len(value) > limit:
        raise HTTPException(400, f"at most {limit} {what} per request")
    return value


def parse_body(body, max_series_points):
    """``(verstrs, keys, max_points)`` from a request body, or a 400."""
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    verstrs = _string_list(body.get("verstrs"), "verstrs", MAX_RUNS)
    bad = next((v for v in verstrs if not safe_segment(v)), None)
    if bad is not None:
        raise HTTPException(400, f"Invalid version '{bad}'")
    keys = body.get("keys")
    if keys is not None:
        keys = _string_list(keys, "keys")
    max_points = body.get("max_points", detail_reader.DEFAULT_MAX_POINTS)
    if not isinstance(max_points, int) or isinstance(max_points, bool):
        raise HTTPException(400, "max_points must be an integer")
    return list(dict.fromkeys(verstrs)), keys, max(2, min(max_points, max_series_points))


def batch_series(storage, app_name, verstrs, keys, max_points):
    """The response payload; runs are read concurrently on a bounded pool and
    share the per-response points cap."""
    budget = max(series_reader.MAX_TOTAL_POINTS // max(len(verstrs), 1), 2)

    def one(verstr):
        return detail_reader.run_series(storage, app_name, verstr, keys, max_points, budget)

    payload = {"series": {}, "series_total": {}, "missing": []}
    for verstr, found in zip(verstrs, _POOL.map(one, verstrs)):
        if found is None:
            payload["missing"].append(verstr)
        else:
            payload["series"][verstr], payload["series_total"][verstr] = found
    return payload


def register(app, prefix, storage_for, max_series_points):
    """Add the route; *storage_for(ws_name, app_tag)* → ``(storage, app_name)``."""

    @app.post(f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}/series")
    def experiment_series(ws_name: str, app_tag: str, body: dict, request: Request):
        storage, app_name = storage_for(ws_name, app_tag)
        verstrs, keys, max_points = parse_body(body, max_series_points)
        payload = batch_series(storage, app_name, verstrs, keys, max_points)
        return json_response(payload, request=request)
