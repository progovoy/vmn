#!/usr/bin/env python3
"""The min/max LOD pyramid of an indexed metric file (plan 12 §3.2, D4).

Buckets are the ones the UI's ``SeriesThinner`` builds: they span ``size``
points aligned from the second point (the first and last points are always
kept on their own), hold the first of equal minima/maxima over finite values,
and only full buckets ending before the last point exist. A bucket without
finite values carries its first point as both extremes, ``n_finite`` 0.
Each bucket is 8 float64: min_v, min_step, min_ts, max_v, max_step, max_ts,
n_finite, sum (a step-less key stores NaN steps).
"""
import math
from typing import NamedTuple

from vmn_exp.core.metric_columns import pack_floats, unpack_floats

BUCKET_FIELDS = 8


class Bucket(NamedTuple):
    min_v: float
    min_step: float
    min_ts: float
    max_v: float
    max_step: float
    max_ts: float
    n_finite: float
    sum: float


def _step(cols, i):
    return float(cols.steps[i]) if cols.steps is not None else math.nan


def summarize(cols, start, end):
    """The :class:`Bucket` of positions ``[start, end)`` of *cols*."""
    values = cols.values
    lo = hi = None
    finite = []
    for i in range(start, end):
        value = values[i]
        if not math.isfinite(value):
            continue
        finite.append(value)
        if lo is None or value < values[lo]:
            lo = i
        if hi is None or value > values[hi]:
            hi = i
    if lo is None:
        lo = hi = start
    return Bucket(
        values[lo], _step(cols, lo), float(cols.ts[lo]),
        values[hi], _step(cols, hi), float(cols.ts[hi]),
        float(len(finite)), math.fsum(finite),
    )


def merge(a, b):
    """The bucket of two adjacent buckets, *a* first."""
    if not b.n_finite:
        return a
    if not a.n_finite:
        return b
    low = b if b.min_v < a.min_v else a
    high = b if b.max_v > a.max_v else a
    return Bucket(*low[:3], *high[3:6], a.n_finite + b.n_finite, a.sum + b.sum)


def level_buckets(cols, size, finer=None, finer_size=None):
    """All full buckets of *size*; merged from a *finer* level when given."""
    count = max(len(cols) - 2, 0) // size
    if finer is None:
        return [summarize(cols, 1 + k * size, 1 + (k + 1) * size) for k in range(count)]
    ratio = size // finer_size
    out = []
    for k in range(count):
        group = finer[k * ratio : (k + 1) * ratio]
        bucket = group[0]
        for other in group[1:]:
            bucket = merge(bucket, other)
        out.append(bucket)
    return out


def encode_buckets(buckets):
    return pack_floats([x for bucket in buckets for x in bucket])


def decode_buckets(data):
    flat = unpack_floats(data)
    return [
        Bucket(*flat[i : i + BUCKET_FIELDS]) for i in range(0, len(flat), BUCKET_FIELDS)
    ]


def _as_point(value, step, ts):
    return {"step": None if math.isnan(step) else int(step), "value": value, "ts": int(ts)}


def emit(bucket):
    """A bucket's extremes as points in series order (one if they coincide)."""
    low = _as_point(*bucket[:3])
    if not bucket.n_finite:
        return [low]
    high = _as_point(*bucket[3:6])
    if (low["step"], low["ts"]) == (high["step"], high["ts"]):
        return [low]
    order = lambda p: (p["step"] if p["step"] is not None else 0, p["ts"])  # noqa: E731
    return sorted([low, high], key=order)
