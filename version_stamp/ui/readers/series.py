#!/usr/bin/env python3
"""Thinning a metric series for charting without losing its shape.

A run that logs every step can carry hundreds of thousands of points per
metric; a chart is a few thousand pixels wide. Min/max bucketing keeps each
bucket's extremes, so a loss spike or a collapse survives however hard the
series is thinned — plain striding would step over it.
"""
import math

DEFAULT_MAX_POINTS = 2000
# Points one response may carry across all its metrics.
MAX_TOTAL_POINTS = 200_000


def _finite(point):
    value = point.get("value")
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _summarize(bucket):
    """``(lo, hi)`` positions of a bucket's min and max finite values (the
    first of equals), or ``(None, None)`` when it has none."""
    lo = hi = None
    for i, point in enumerate(bucket):
        if not _finite(point):
            continue
        value = point["value"]
        if lo is None or value < bucket[lo]["value"]:
            lo = i
        if hi is None or value > bucket[hi]["value"]:
            hi = i
    return lo, hi


def _merge(points, a, b):
    """The summary of two adjacent buckets (absolute positions) from theirs."""
    (lo_a, hi_a), (lo_b, hi_b) = a, b
    value = lambda i: points[i]["value"]  # noqa: E731
    lo = lo_b if lo_a is None or (lo_b is not None and value(lo_b) < value(lo_a)) else lo_a
    hi = hi_b if hi_a is None or (hi_b is not None and value(hi_b) > value(hi_a)) else hi_a
    return lo, hi


def _absolute(summary, offset):
    return tuple(None if i is None else i + offset for i in summary)


def _emit(points, start, summary):
    """A bucket's extremes in their original order; its first point if none."""
    lo, hi = summary
    if lo is None:
        return [points[start]]
    return [points[i] for i in sorted({lo, hi})]


class SeriesThinner:
    """Min/max thinning of one growing series, extended as it grows.

    Buckets span a power-of-two number of interior points, aligned from the
    first interior point, so a grown series only summarizes its new points —
    and when the bucket count would exceed the budget, adjacent buckets merge
    pairwise. :func:`downsample` is this over the whole series, so both always
    agree.
    """

    def __init__(self, max_points=DEFAULT_MAX_POINTS):
        self.max_points = max(int(max_points), 2)
        self.n_buckets = (self.max_points - 2) // 2
        self._size, self._buckets, self._count = 1, [], 0

    def thin(self, points, count):
        """At most ``max_points`` of ``points[:count]``, first and last kept."""
        if count <= self.max_points:
            return points[:count]
        if count < self._count:  # an older view: its own, one-off thinning
            return SeriesThinner(self.max_points).thin(points, count)
        self._count = count
        if not self.n_buckets:
            return [points[0], points[count - 1]]
        self._grow_to(points, count)
        kept = [points[0]]
        for k, summary in enumerate(self._buckets):
            kept.extend(_emit(points, 1 + k * self._size, summary))
        tail = 1 + len(self._buckets) * self._size
        if tail < count - 1:
            summary = _absolute(_summarize(points[tail : count - 1]), tail)
            kept.extend(_emit(points, tail, summary))
        kept.append(points[count - 1])
        return kept

    def _grow_to(self, points, count):
        interior = count - 2
        while -(-interior // self._size) > self.n_buckets:
            self._size *= 2
            pairs = self._buckets
            self._buckets = [
                _merge(points, pairs[i], pairs[i + 1]) for i in range(0, len(pairs) - 1, 2)
            ]
        start = 1 + len(self._buckets) * self._size
        while start + self._size <= count - 1:
            bucket = points[start : start + self._size]
            self._buckets.append(_absolute(_summarize(bucket), start))
            start += self._size


def downsample(points, max_points=DEFAULT_MAX_POINTS):
    """At most *max_points* of *points*, first and last always kept."""
    return SeriesThinner(max_points).thin(points, len(points))


def points_per_metric(max_points, n_metrics, budget=None):
    """*max_points*, lowered so *n_metrics* series stay within *budget* points
    (default :data:`MAX_TOTAL_POINTS`)."""
    budget = MAX_TOTAL_POINTS if budget is None else budget
    share = budget // max(n_metrics, 1)
    return max(2, min(int(max_points), share))
