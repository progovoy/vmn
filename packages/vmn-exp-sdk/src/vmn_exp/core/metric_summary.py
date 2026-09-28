#!/usr/bin/env python3
"""Which value of a metric a row ranks on: its summary policy.

The fold keeps each metric's last value and, once a second value arrives, its
finite ``(min, max)``. A metric's *summary policy* picks one of the three for
``row["metrics"]`` — so sorting, ``--query metrics.x``, the leaderboard and
compare all rank on the best value, not merely the latest.

The policy comes from, in order: the run's own ``define_metric`` log entries
(``run.define_metric()`` in the SDK — latest wins), the app's metrics schema
(``experiment.metrics`` in conf.yml), and finally ``last``. Within one
definition an explicit ``summary`` beats one derived from ``goal``
(``goal: min`` -> ``min``, ``goal: max`` -> ``max``).

Non-finite values (NaN/inf) stay in the log and may be a metric's last value,
but never its min or max. A ``min``/``max`` policy on a metric without any
finite value falls back to the last value, which then sorts last.
Pure: no storage, no clock beyond an entry's timestamp.
"""
import math

from vmn_exp._base import now_iso

DEFINE_METRIC = "define_metric"
SUMMARIES = ("min", "max", "last")
GOALS = ("min", "max")


def define_metric_entry(name, summary=None, goal=None):
    """A ``define_metric`` log entry: *name*'s summary policy and/or goal."""
    if not isinstance(name, str) or not name:
        raise ValueError(f"Metric names must be non-empty strings, got {name!r}")
    if summary is None and goal is None:
        raise ValueError("define_metric needs a summary and/or a goal")
    if summary is not None and summary not in SUMMARIES:
        raise ValueError(f"summary must be one of {SUMMARIES}, got {summary!r}")
    if goal is not None and goal not in GOALS:
        raise ValueError(f"goal must be one of {GOALS}, got {goal!r}")
    entry = {"timestamp": now_iso(), "type": DEFINE_METRIC, "name": name}
    if summary is not None:
        entry["summary"] = summary
    if goal is not None:
        entry["goal"] = goal
    return entry


def entry_definition(entry):
    """``(name, {"summary", "goal"})`` of a ``define_metric`` entry, or None."""
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        return None
    return name, {"summary": entry.get("summary"), "goal": entry.get("goal")}


def _policy_of(definition):
    """The summary a definition asks for, or None when it asks for none."""
    if not isinstance(definition, dict):
        return None
    summary = definition.get("summary")
    if summary in SUMMARIES:
        return summary
    goal = definition.get("goal")
    return goal if goal in GOALS else None


def metric_policy(name, run_defs, schema):
    """*name*'s summary policy: the run's definition, the schema's, else ``last``."""
    return (
        _policy_of(run_defs.get(name))
        or _policy_of((schema or {}).get(name))
        or "last"
    )


def _finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _widen(bounds, value):
    low, high = bounds
    if not _finite(value):
        return low, high
    return (
        value if low is None or value < low else low,
        value if high is None or value > high else high,
    )


def track_extrema(extrema, name, value):
    """Widen *name*'s entry in *extrema* by one logged *value*.

    A metric logged once keeps that value bare — the float the fold already
    holds, so most rows cost no more than before; the second value turns it
    into ``(min, max)``. Only logged values count: a numeric param folded into
    ``metrics`` under the same name never widens the bounds.
    """
    seen = extrema.get(name)
    if seen is None:
        extrema[name] = value
        return
    bounds = tuple(seen) if isinstance(seen, (list, tuple)) else _widen((None, None), seen)
    extrema[name] = _widen(bounds, value)


def _bounds(seen, last):
    """``(min, max, logged more than once)`` for an extrema entry."""
    if isinstance(seen, (list, tuple)):
        return seen[0], seen[1], True
    low, high = _widen((None, None), last if seen is None else seen)
    return low, high, False


def summarize(last_values, extrema, run_defs, schema):
    """``(metrics, metric_summary)`` of a fold's metrics.

    *metrics* maps each metric to its policy's value; *metric_summary* maps
    each metric seen more than once to ``{"last", "min", "max"}``.
    """
    metrics, summary = {}, {}
    for name, last in last_values.items():
        low, high, repeated = _bounds(extrema.get(name), last)
        if repeated:
            summary[name] = {"last": last, "min": low, "max": high}
        policy = metric_policy(name, run_defs, schema)
        best = low if policy == "min" else high if policy == "max" else None
        metrics[name] = last if best is None else best
    return metrics, summary
