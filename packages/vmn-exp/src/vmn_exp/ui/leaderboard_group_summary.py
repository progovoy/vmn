#!/usr/bin/env python3
"""A group's counts and aggregates, kept as the group's rows come and go.

A :class:`Summary` holds each metric's finite values sorted, how many rows
carry each metric, and a status tally. Rows join and leave in
O(metrics · log n) (plus a C-speed list shift), so a sweep of tens of
thousands of runs is not summarized from all its rows again whenever one
changes; ``min``/``max``/``median`` are read off the sorted values and the
mean is an exact ``fsum`` of them, so it equals a fresh summary's bit for bit.
Copies share the value lists until one is written (copy-on-write).
"""
import bisect
import math

from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.core.settle import counted_status
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.leaderboard_group_fields import COUNT_KEYS, COUNT_OF


def _median(ordered):
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _of_sorted(ordered, agg, goal):
    if not ordered:
        return None
    if agg == "best":
        agg = goal if goal in ("min", "max") else "mean"
    if agg == "min":
        return ordered[0]
    if agg == "max":
        return ordered[-1]
    if agg == "median":
        return _median(ordered)
    return math.fsum(ordered) / len(ordered)


def stats(ordered, goal):
    """Every aggregate of sorted finite *ordered*; ``best`` follows *goal*."""
    best = _of_sorted(ordered, goal, goal) if goal in ("min", "max") else None
    return {"mean": _of_sorted(ordered, "mean", goal), "best": best,
            "median": _of_sorted(ordered, "median", goal), "min": _of_sorted(ordered, "min", goal),
            "max": _of_sorted(ordered, "max", goal), "n": len(ordered)}


class Summary:
    __slots__ = ("_owned", "carriers", "size", "statuses", "values")

    def __init__(self, values=None, carriers=None, statuses=None, size=0):
        self.values = values or {}  # {metric: sorted finite values}
        self.carriers = carriers or {}  # {metric: rows carrying it}
        self.statuses = statuses or {}
        self.size = size
        self._owned = set()

    @classmethod
    def of(cls, rows):
        summary = cls()
        values = summary.values
        for row in rows:
            summary._tally(row, 1)
            for metric, value in row["metrics"].items():
                if is_finite_number(value):
                    values.setdefault(metric, []).append(value)
        for kept in values.values():
            kept.sort()
        summary._owned = set(values)
        return summary

    def copy(self):
        return Summary(dict(self.values), dict(self.carriers), dict(self.statuses), self.size)

    def _tally(self, row, by):
        self.size += by
        status = counted_status(row)
        self.statuses[status] = self.statuses.get(status, 0) + by
        for metric in row["metrics"]:
            self.carriers[metric] = self.carriers.get(metric, 0) + by

    def _list(self, metric):
        if metric not in self._owned:
            self.values[metric] = list(self.values.get(metric, ()))
            self._owned.add(metric)
        return self.values[metric]

    def add(self, rows):
        for row in rows:
            self._tally(row, 1)
            for metric, value in row["metrics"].items():
                if is_finite_number(value):
                    bisect.insort(self._list(metric), value)
        return self

    def remove(self, rows):
        for row in rows:
            self._tally(row, -1)
            for metric, value in row["metrics"].items():
                if is_finite_number(value):
                    kept = self._list(metric)
                    del kept[bisect.bisect_left(kept, value)]
        return self

    def with_rows(self, rows):
        """This summary plus *rows*, without changing it."""
        return self.copy().add(rows) if rows else self

    def counts(self):
        out = dict.fromkeys(COUNT_KEYS, 0)
        for status, count in self.statuses.items():
            if status in COUNT_OF:
                out[COUNT_OF[status]] += count
        out["total"] = self.size
        return out

    def value(self, metric, agg, goal):
        return _of_sorted(self.values.get(metric) or [], agg, goal)

    def aggregates(self, schema):
        """``{metric: stats}`` for every metric a row of the group carries."""
        return {metric: stats(self.values.get(metric) or [], metric_goal(schema, metric))
                for metric, carrying in self.carriers.items() if carrying}
