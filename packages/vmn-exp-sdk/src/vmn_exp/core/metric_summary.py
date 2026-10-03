#!/usr/bin/env python3
"""Which value of a metric a row ranks on: its summary policy.

The fold keeps each metric's last value and, once a second value arrives, its
finite min, max, count and exact sum, and its earliest value. A metric's *summary
policy* picks one of ``last``/``min``/``max``/``first``/``mean`` for
``row["metrics"]`` — so sorting, ``--query metrics.x``, the leaderboard and
compare all rank on the chosen value, not merely the latest.

The policy comes from, in order: the run's own ``define_metric`` log entries
(``run.define_metric()`` in the SDK, the same entry that declares a
``step_metric`` — see :mod:`vmn_exp.core.step_metric`), the app's metrics
schema (``experiment.metrics`` in conf.yml), and finally ``last``. Within
each, an exact metric name beats a glob (``val_*``, the latest-declared
matching one), and an explicit ``summary`` beats one derived from ``goal``
(``goal: min`` -> ``min``, ``goal: max`` -> ``max``). Declarations fold per
field, last write wins, so declaring a ``step_metric`` later keeps the summary.

``first`` is the earliest value by the fold key (timestamp, writer, position),
so writers may fold in any order. Non-finite values (NaN/inf) stay in the log
and may be a metric's last or first value, but never its min, max or part of
its mean. A ``min``/``max``/``mean`` policy on a metric without any finite
value falls back to the last value, which then sorts last.
Pure: no storage, no clock beyond an entry's timestamp.
"""
import math

from vmn_exp.core.metric_columns import add_exact as _add_exact
from vmn_exp.core.step_metric import lookup
from vmn_exp.core.values import is_finite_number

SUMMARIES = ("min", "max", "last", "first", "mean")
GOALS = ("min", "max")
_BEST = ("min", "max", "first", "mean")  # the policies that can beat "last"


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


_EMPTY = (None, None, 0)


def _widen(seen, value):
    """*seen* — ``(min, max, n, *partial sums)`` of the finite values so far —
    widened by *value*; *seen* itself when *value* is not finite."""
    if not is_finite_number(value):
        return seen
    low, high, n = seen[:3]
    return (
        value if low is None or value < low else low,
        value if high is None or value > high else high,
        n + 1,
    ) + _add_exact(seen[3:], value)


def _repeated(seen):
    """Whether an extrema entry holds ``(min, max, n, *sums)``: the metric was
    logged twice."""
    return isinstance(seen, (list, tuple))


def _keep_first(firsts, name, value, key):
    """Keep ``(value, *key)`` under *name* unless an earlier key holds it."""
    current = firsts.get(name)
    if current is None or key < tuple(current[1:]):
        firsts[name] = (value,) + key


def _key_of(fold, name):
    """The fold key of *name*'s ``metrics`` entry, or None."""
    current = fold["metrics"].get(name)
    return tuple(current[1:]) if current is not None else None


def track_extrema(fold, name, value, key):
    """Widen *name*'s ``extrema`` entry in *fold* by one logged *value* at
    fold *key*, keeping its earliest value in ``firsts``.

    A metric logged once keeps that value bare — the float the fold already
    holds, so most rows cost no more than before; the second value turns it
    into ``(min, max, n, *sums)`` and seeds ``firsts``. The bare value's key
    is the one its ``metrics`` entry (not yet updated with *value*) holds —
    unless a same-named param holds that entry, in which case ``firsts`` got
    the bare value when the param took it (see :func:`note_param`). Only
    logged values count: a numeric param never widens the bounds.
    """
    extrema = fold.setdefault("extrema", {})
    seen = extrema.get(name)
    if seen is None:
        extrema[name] = value
        held = _key_of(fold, name)
        if held is not None and key < held:  # a later param holds metrics[name]
            fold.setdefault("firsts", {})[name] = (value,) + key
        return
    firsts = fold.setdefault("firsts", {})
    if not _repeated(seen):
        if name not in firsts:
            firsts[name] = (seen,) + _key_of(fold, name)
        seen = _widen(_EMPTY, seen)
    _keep_first(firsts, name, value, key)
    extrema[name] = _widen(tuple(seen), value)


def track_block(fold, name, first, first_key, finite):
    """Widen *name*'s ``extrema`` by a whole block of at least two points
    (plan 12 §5.3): its earliest value *first* at *first_key* and its
    *finite* ``{n, sum, parts, min, max}`` summary — what
    :func:`track_extrema` point by point would give, exactly."""
    extrema = fold.setdefault("extrema", {})
    firsts = fold.setdefault("firsts", {})
    seen = extrema.get(name)
    if seen is None:
        seen = _EMPTY
    elif not _repeated(seen):
        if name not in firsts:
            firsts[name] = (seen,) + _key_of(fold, name)
        seen = _widen(_EMPTY, seen)
    _keep_first(firsts, name, first, first_key)
    extrema[name] = _widen_by_summary(tuple(seen), finite)


def _widen_by_summary(seen, finite):
    if not finite.get("n"):
        return seen
    low, high, n = seen[:3]
    block_low, block_high = finite["min"][0], finite["max"][0]
    partials = seen[3:]
    for part in finite.get("parts") or [finite["sum"]]:
        partials = _add_exact(partials, part)
    return (
        block_low if low is None or block_low < low else low,
        block_high if high is None or block_high > high else high,
        n + finite["n"],
    ) + partials


def note_param(fold, name, key):
    """Before a numeric param at fold *key* takes ``metrics[name]``: keep a
    metric logged once so far (its value and key) in ``firsts``, which is
    the only place its key would survive."""
    seen = (fold.get("extrema") or {}).get(name)
    if seen is None or _repeated(seen) or name in (fold.get("firsts") or {}):
        return
    held = _key_of(fold, name)
    if held is not None and key >= held:
        fold.setdefault("firsts", {})[name] = (seen,) + held


def _summary_of(last, seen, first):
    low, high, n = seen[:3]
    return {
        "last": last, "min": low, "max": high,
        "first": last if first is None else first[0],
        "mean": math.fsum(seen[3:]) / n if n else None,
    }


def summarize(last_values, extrema, run_defs, schema, firsts=None):
    """``(metrics, metric_summary)`` of a fold's metrics.

    *metrics* maps each metric to its policy's value; *metric_summary* maps
    each metric seen more than once to ``{"last", "min", "max", "first",
    "mean"}`` (*firsts* being the fold's earliest values).
    """
    firsts = firsts or {}
    summary = {
        name: _summary_of(last_values[name], seen, firsts.get(name))
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
        best = seen[policy] if policy in _BEST else None
        value = seen["last"] if best is None else best
        if value is not metrics.get(name):
            picked[name] = value
    return {**metrics, **picked} if picked else metrics
