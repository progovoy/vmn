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
from vmn_exp.core.step_metric import lookup
from vmn_exp.core.values import is_finite_number

SUMMARIES = ("min", "max", "last")
GOALS = ("min", "max")


def summary_fields(summary=None, goal=None):
    """``{"summary"?, "goal"?}`` for a ``define_metric`` entry; ValueError on
    anything but the known policies."""
    if summary is not None and summary not in SUMMARIES:
        raise ValueError(f"summary must be one of {SUMMARIES}, got {summary!r}")
    if goal is not None and goal not in GOALS:
        raise ValueError(f"goal must be one of {GOALS}, got {goal!r}")
    fields = {"summary": summary, "goal": goal}
    return {k: v for k, v in fields.items() if v is not None}


def _policy_of(definition):
    """The summary a definition asks for, or None when it asks for none."""
    if not isinstance(definition, dict):
        return None
    summary = definition.get("summary")
    if summary in SUMMARIES:
        return summary
    goal = definition.get("goal")
    return goal if goal in GOALS else None


def _widen(bounds, value):
    """*bounds* widened by *value* — *bounds* itself when that changes nothing."""
    low, high = bounds
    if not is_finite_number(value) or (low is not None and low <= value <= high):
        return bounds
    return (
        value if low is None or value < low else low,
        value if high is None or value > high else high,
    )


def _repeated(seen):
    """Whether an extrema entry holds ``(min, max)``: the metric was logged twice."""
    return isinstance(seen, (list, tuple))


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
    bounds = seen if _repeated(seen) else _widen((None, None), seen)
    widened = _widen(bounds, value)
    if widened is not seen:
        extrema[name] = tuple(widened)


def summarize(last_values, extrema, run_defs, schema):
    """``(metrics, metric_summary)`` of a fold's metrics.

    *metrics* maps each metric to its policy's value; *metric_summary* maps
    each metric seen more than once to ``{"last", "min", "max"}``.
    """
    summary = {
        name: {"last": last_values[name], "min": seen[0], "max": seen[1]}
        for name, seen in extrema.items()
        if _repeated(seen)
    }
    return with_policies(last_values, summary, run_defs, schema), summary


def with_policies(metrics, summary, run_defs, schema):
    """*metrics* with each metric of *summary* at its policy's value — the
    run's definitions first, then *schema*. Only a metric logged more than
    once can differ from its last value, so the rest are left as they are;
    *metrics* itself comes back when no value changes."""
    if not summary or not (run_defs or schema):
        return metrics
    picked = {}
    for name, seen in summary.items():
        policy = lookup(name, run_defs or {}, _policy_of) or lookup(
            name, schema or {}, _policy_of
        )
        best = seen[policy] if policy in GOALS else None
        value = seen["last"] if best is None else best
        if value is not metrics.get(name):
            picked[name] = value
    return {**metrics, **picked} if picked else metrics
