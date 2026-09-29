#!/usr/bin/env python3
"""Which value of a metric a row ranks on: its summary policy.

The fold keeps each metric's last value and, once a second value arrives, its
finite ``(min, max)``. A metric's *summary policy* picks one of the three for
``row["metrics"]`` — so sorting, ``--query metrics.x``, the leaderboard and
compare all rank on the best value, not merely the latest.

The policy comes from, in order: the run's own ``define_metric`` log entries
(``run.define_metric()`` in the SDK, the same entry that declares a
``step_metric`` — see :mod:`vmn_exp.core.step_metric`), the app's metrics
schema (``experiment.metrics`` in conf.yml), and finally ``last``. Within
each, an exact metric name beats a glob (``val_*``, the latest-declared
matching one), and an explicit ``summary`` beats one derived from ``goal``
(``goal: min`` -> ``min``, ``goal: max`` -> ``max``). Declarations fold per
field, last write wins, so declaring a ``step_metric`` later keeps the summary.

Non-finite values (NaN/inf) stay in the log and may be a metric's last value,
but never its min or max. A ``min``/``max`` policy on a metric without any
finite value falls back to the last value, which then sorts last.
Pure: no storage, no clock beyond an entry's timestamp.
"""
import math
import re
from fnmatch import fnmatchcase

from vmn_exp.core.step_metric import DEFINE_METRIC, create_define_metric_entry  # noqa: F401

SUMMARIES = ("min", "max", "last")
GOALS = ("min", "max")
POLICY_FIELDS = ("summary", "goal")
_GLOB = re.compile(r"[*?\[]")


def summary_fields(summary=None, goal=None):
    """``{"summary"?, "goal"?}`` for a ``define_metric`` entry; ValueError on
    anything but the known policies."""
    if summary is not None and summary not in SUMMARIES:
        raise ValueError(f"summary must be one of {SUMMARIES}, got {summary!r}")
    if goal is not None and goal not in GOALS:
        raise ValueError(f"goal must be one of {GOALS}, got {goal!r}")
    fields = {"summary": summary, "goal": goal}
    return {k: v for k, v in fields.items() if v is not None}


def define_metric_entry(name, summary=None, goal=None, **fields):
    """A ``define_metric`` log entry declaring *name*'s summary and/or goal
    (plus any other declaration *fields*, e.g. ``step_metric``)."""
    if summary is None and goal is None:
        raise ValueError("define_metric needs a summary and/or a goal")
    return create_define_metric_entry(name, **summary_fields(summary, goal), **fields)


def entry_definition(entry):
    """``(name, {field: value})`` of the policy fields a ``define_metric``
    entry sets, or None."""
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        return None
    fields = {k: entry[k] for k in POLICY_FIELDS if entry.get(k) is not None}
    return (name, fields) if fields else None


def _policy_of(definition):
    """The summary a definition asks for, or None when it asks for none."""
    if not isinstance(definition, dict):
        return None
    summary = definition.get("summary")
    if summary in SUMMARIES:
        return summary
    goal = definition.get("goal")
    return goal if goal in GOALS else None


def _globs(declarations):
    """The glob patterns of *declarations*, latest-declared first."""
    return [p for p in reversed(list(declarations)) if _GLOB.search(p)]


def _declared(metric, declarations, globs):
    policy = _policy_of(declarations.get(metric))
    if policy:
        return policy
    for pattern in globs:
        if fnmatchcase(metric, pattern):
            policy = _policy_of(declarations[pattern])
            if policy:
                return policy
    return None


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
    if not run_defs and not schema:  # every metric is `last`: skip the policy lookups
        return last_values, {
            name: {"last": last_values[name], "min": seen[0], "max": seen[1]}
            for name, seen in extrema.items()
            if isinstance(seen, (list, tuple))
        }
    schema = schema or {}
    run_globs, schema_globs = _globs(run_defs), _globs(schema)
    metrics, summary = {}, {}
    for name, last in last_values.items():
        low, high, repeated = _bounds(extrema.get(name), last)
        if repeated:
            summary[name] = {"last": last, "min": low, "max": high}
        policy = (
            _declared(name, run_defs, run_globs)
            or _declared(name, schema, schema_globs)
            or "last"
        )
        best = low if policy == "min" else high if policy == "max" else None
        metrics[name] = last if best is None else best
    return metrics, summary
