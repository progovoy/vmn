#!/usr/bin/env python3
"""Thinning a metric series for charting without losing its shape.

A run that logs every step can carry hundreds of thousands of points per
metric; a chart is a few thousand pixels wide. Min/max bucketing keeps each
bucket's extremes, so a loss spike or a collapse survives however hard the
series is thinned — plain striding would step over it.
"""
import math

DEFAULT_MAX_POINTS = 2000


def _finite(point):
    value = point.get("value")
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _extremes(bucket):
    """A bucket's min and max points in their original order (one if equal)."""
    numeric = [p for p in bucket if _finite(p)]
    if not numeric:
        return bucket[:1]
    lo = min(numeric, key=lambda p: p["value"])
    hi = max(numeric, key=lambda p: p["value"])
    if lo is hi:
        return [lo]
    return [p for p in bucket if p is lo or p is hi]


def downsample(points, max_points=DEFAULT_MAX_POINTS):
    """At most *max_points* of *points*, first and last always kept."""
    max_points = max(int(max_points), 2)
    if len(points) <= max_points:
        return list(points)

    interior = points[1:-1]
    n_buckets = max((max_points - 2) // 2, 1)
    size = math.ceil(len(interior) / n_buckets)
    kept = [points[0]]
    for start in range(0, len(interior), size):
        kept.extend(_extremes(interior[start : start + size]))
    kept.append(points[-1])
    return kept


def downsample_series(series, max_points=DEFAULT_MAX_POINTS):
    """``(thinned series, {metric: original point count})`` — each metric alone."""
    thinned = {key: downsample(points, max_points) for key, points in series.items()}
    return thinned, {key: len(points) for key, points in series.items()}
