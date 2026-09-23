#!/usr/bin/env python3
"""JSON responses that survive non-finite floats.

Metrics are truthfully stored as NaN/inf when a run diverges, but strict JSON
has no token for them and Starlette refuses to emit one — so a single NaN
anywhere in a payload used to turn the whole leaderboard into a 500. Here they
go out as ``null``, which every client already treats as "no value".
"""
import json
import math

from fastapi.responses import JSONResponse


def _finite_or_none(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite_or_none(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_or_none(v) for v in value]
    return value


def _dumps(content):
    return json.dumps(
        content, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


class SafeJSONResponse(JSONResponse):
    def render(self, content):
        try:
            return _dumps(content)  # fast path: nothing to scrub
        except ValueError:
            return _dumps(_finite_or_none(content))
