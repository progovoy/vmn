#!/usr/bin/env python3
"""The additive parts a job rollup is made of (plan 23 S1).

A :class:`Tally` sums what a set of rows contributes: status counts (a
settled row's under its ``settled`` value), first
start and last end, completions per minute, per tracked metric its count,
sum, extremes and a :class:`~vmn_exp.ui.quantile_sketch.QuantileSketch`, a
duration sketch and failure-signature counts. ``add(row, spec, by=-1)``
takes a row back out. Counts and sketches are exact under removal; an
extreme (min/max/best, first start, last end) is not, so a removal that
takes away the last row holding one reports it and the caller recomputes
that tally from its rows.
"""
import math
import operator

from vmn_exp.core.log import primary_metric, sort_descending
from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.core.settle import counted_status
from vmn_exp.core.status import (
    CREATED,
    FAILED,
    RUNNING,
    RELEASED,
    STUCK,
    SUCCEEDED,
    parse_iso,
)
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.failure_signature import signature
from vmn_exp.ui.quantile_sketch import QuantileSketch

DONE = (SUCCEEDED, FAILED)
# A job's states (D12), as the rollup names them.
STATES = {RUNNING: "running", CREATED: "waiting", SUCCEEDED: "succeeded",
          FAILED: "failed", STUCK: "stuck"}
# What a job's timeline counts per minute: runs started, runs ended per
# outcome, and runs handed back unfinished (their last release, plan 28 API2).
TIMELINE = ("started", SUCCEEDED, FAILED, RELEASED)
MINUTES_KEPT = 24 * 60
COARSE_MINUTES = 10


def _is_glob(name):
    return any(c in name for c in "*?[")


FALLBACK_METRICS = 5


class RollupSpec:
    """What a schema makes a rollup track: its goal metrics (exact names)
    and primary metric, each with its direction; ``main`` names the one a
    compact summary shows. A schema without any tracks the app's
    :data:`FALLBACK_METRICS` most *common()* metrics instead, goal-less
    (``ranked`` False: no best, nothing to rank — plan 20)."""

    def __init__(self, schema, common=tuple):
        schema = schema or {}
        names = {m for m in schema if not _is_glob(m) and metric_goal(schema, m)}
        primary = primary_metric(schema)
        names.update([primary] if primary else [])
        self.ranked = bool(names)
        self.metrics = tuple(sorted(names)) if names else tuple(common())[:FALLBACK_METRICS]
        self.descending = {m: sort_descending(schema, m) for m in self.metrics}
        self.main = primary or (self.metrics[0] if self.metrics else None)

    def same_metrics(self, other):
        return (self.metrics, self.main, self.ranked) == (other.metrics, other.main, other.ranked)


def _extreme(current, value, by, better):
    """``(value, rows holding it)`` after adding (*by* > 0) or removing
    *value*, and whether the extreme is now unknown."""
    if value is None:
        return current, False
    if by > 0:
        if current is None or better(value, current[0]):
            return (value, by), False
        return ((value, current[1] + by) if value == current[0] else current), False
    if current is not None and value == current[0]:
        left = current[1] + by
        return ((value, left), False) if left > 0 else (None, True)
    return current, False


def higher_first(a, b):
    """Higher value wins; on a tie the lower verstr does."""
    return a[0] > b[0] or (a[0] == b[0] and a[1] < b[1])


class MetricTally:
    __slots__ = ("high", "low", "n", "sketch", "total")

    def __init__(self):
        self.n, self.total = 0, 0.0
        self.low = self.high = None  # ((value, verstr), 1)
        self.sketch = QuantileSketch()

    def copy(self):
        out = MetricTally()
        out.n, out.total, out.low, out.high = self.n, self.total, self.low, self.high
        out.sketch = self.sketch.copy()
        return out

    def add(self, value, verstr, by):
        """Whether removing *value* left an extreme unknown."""
        self.n += by
        self.total += by * value
        self.sketch.add(value, by)
        self.low, low_gone = _extreme(self.low, (value, verstr), by, operator.lt)
        self.high, high_gone = _extreme(self.high, (value, verstr), by, higher_first)
        return low_gone or high_gone


class Completions:
    """Completions per minute for the last :data:`MINUTES_KEPT` minutes
    (before the newest), and per :data:`COARSE_MINUTES` for all time."""

    __slots__ = ("coarse", "horizon", "minutes")

    def __init__(self):
        self.minutes, self.coarse, self.horizon = {}, {}, -math.inf

    def copy(self):
        out = Completions()
        out.minutes, out.coarse, out.horizon = dict(self.minutes), dict(self.coarse), self.horizon
        return out

    def add(self, minute, by):
        _move(self.coarse, minute // COARSE_MINUTES, by)
        if minute < self.horizon:
            return
        _move(self.minutes, minute, by)
        self.horizon = max(self.horizon, minute - MINUTES_KEPT)
        if len(self.minutes) > MINUTES_KEPT + 60:
            self.minutes = {m: n for m, n in self.minutes.items() if m >= self.horizon}

    def recent(self, now_minute, window):
        """Completions in the *window* minutes up to *now_minute*."""
        start = now_minute - window + 1
        if start >= self.horizon:
            return sum(self.minutes.get(m, 0) for m in range(start, now_minute + 1))
        span = range(start // COARSE_MINUTES, now_minute // COARSE_MINUTES + 1)
        return sum(self.coarse.get(b, 0) for b in span)


def _move(counts, key, by):
    count = counts.get(key, 0) + by
    if count:
        counts[key] = count
    else:
        counts.pop(key, None)


def _minute(stamp):
    parsed = parse_iso(stamp)
    return None if parsed is None else int(parsed.timestamp() // 60)


class Tally:
    """What a set of rows adds to every job above them."""

    __slots__ = (
        "completions",
        "counts",
        "duration",
        "failures",
        "finished",
        "metrics",
        "started",
        "timeline",
    )

    def __init__(self):
        self.counts, self.metrics, self.failures = {}, {}, {}
        self.started = self.finished = None  # (stamp, rows holding it)
        self.completions = Completions()
        self.timeline = {name: Completions() for name in TIMELINE}
        self.duration = QuantileSketch()

    @classmethod
    def of(cls, rows, spec):
        tally = cls()
        for row in rows:
            tally.add(row, spec)
        return tally

    def copy(self):
        out = Tally()
        out.counts, out.failures = dict(self.counts), dict(self.failures)
        out.started, out.finished = self.started, self.finished
        out.completions, out.duration = self.completions.copy(), self.duration.copy()
        out.timeline = {name: series.copy() for name, series in self.timeline.items()}
        out.metrics = {name: metric.copy() for name, metric in self.metrics.items()}
        return out

    def add(self, row, spec, by=1):
        """Adds *row* (``by=-1``: removes it); whether an extreme is now unknown."""
        status = row.get("status")
        _move(self.counts, counted_status(row), by)
        self.started, gone = _extreme(self.started, row.get("started_at"), by, operator.lt)
        self.finished, ended = _extreme(self.finished, row.get("finished_at"), by, operator.gt)
        unknown = gone or ended
        started = _minute(row["started_at"]) if row.get("started_at") else None
        if started is not None:
            self.timeline["started"].add(started, by)
        released = _minute(row["released_at"]) if row.get("released_at") else None
        if released is not None:
            self.timeline[RELEASED].add(released, by)
        if status in DONE and row.get("finished_at"):
            minute = _minute(row["finished_at"])
            if minute is not None:
                self.completions.add(minute, by)
                self.timeline[status].add(minute, by)
            self.duration.add(row.get("duration_sec"), by)
        metrics = row.get("metrics") or {}
        for name in spec.metrics:
            if is_finite_number(metrics.get(name)):
                unknown = self._add_metric(name, metrics[name], row["verstr"], by) or unknown
        sig = signature(row)
        if sig:
            _move(self.failures, sig, by)
        return unknown

    def _add_metric(self, name, value, verstr, by):
        metric = self.metrics.get(name)
        if metric is None:
            metric = self.metrics[name] = MetricTally()
        unknown = metric.add(value, verstr, by)
        if metric.n <= 0:
            del self.metrics[name]
            return False
        return unknown
