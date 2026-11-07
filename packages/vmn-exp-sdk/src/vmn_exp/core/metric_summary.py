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
value leaves the metric missing, never its last value. A row's
``metric_policy`` names the policy of each value its run's own definition
picked unlike the schema, so a column mixing runs' own summaries can say so.
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
    a same-named param never holds it (see
    :func:`~vmn_exp.core.fold.take_from_param`). Only logged values count: a
    numeric param never widens the bounds.
    """
    extrema = fold.setdefault("extrema", {})
    seen = extrema.get(name)
    if seen is None:
        extrema[name] = value
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


def _summary_of(last, seen, first):
    low, high, n = seen[:3]
    return {
        "last": last, "min": low, "max": high,
        "first": last if first is None else first[0],
        "mean": math.fsum(seen[3:]) / n if n else None,
    }


def summarize(last_values, extrema, run_defs, schema, firsts=None):
    """``(metrics, metric_summary, metric_policy)`` of a fold's metrics.

    *metrics* maps each metric to its policy's value; *metric_summary* maps
    each metric seen more than once to ``{"last", "min", "max", "first",
    "mean"}`` (*firsts* being the fold's earliest values); *metric_policy*
    names each value its run's own definition picked unlike *schema* (see :func:`with_schema_policies`).
    """
    firsts = firsts or {}
    summary = {
        name: _summary_of(last_values[name], seen, firsts.get(name))
        for name, seen in extrema.items()
        if _repeated(seen)
    }
    metrics, policy = with_policies(last_values, summary, run_defs, schema)
    return metrics, summary, policy


def same_value(a, b):
    """Whether *a* and *b* are the same metric value — equal, of one type,
    one sign of zero, or both NaN — not merely the same object (a packed
    summary hands out new ones)."""
    if a is b:
        return True
    if type(a) is not type(b):
        return False
    if a == b:
        return type(a) is not float or math.copysign(1, a) == math.copysign(1, b)
    return a != a and b != b


class SchemaPolicies:
    """Each metric's summary policy under a metrics *schema* — the run's
    definitions first — with the schema's resolved once per metric name, so
    rows sharing names pay a dict lookup per metric, not a glob scan."""

    def __init__(self, schema):
        self._schema = schema or {}
        self._memo = {}

    def __bool__(self):
        return bool(self._schema)

    def column(self, name):
        """*name*'s policy under the schema alone (exact, then glob), else ``last``."""
        try:
            return self._memo[name]
        except KeyError:
            policy = self._memo[name] = lookup(name, self._schema, _policy_of) or "last"
            return policy

    def of(self, name, run_defs=None):
        """*name*'s policy: *run_defs*' (exact, then glob), else the schema's."""
        own = lookup(name, run_defs, _policy_of) if run_defs else None
        return own or self.column(name)


def schema_policy(schema, name):
    """*name*'s summary policy under the metrics *schema* alone, else ``last``."""
    return SchemaPolicies(schema).column(name)


def with_policies(metrics, summary, run_defs, schema):
    """``(metrics, metric_policy)`` of :func:`with_schema_policies` — the
    run's definitions first, then *schema*."""
    return with_schema_policies(metrics, summary, run_defs, SchemaPolicies(schema))


def with_schema_policies(metrics, summary, run_defs, policies):
    """``(metrics, metric_policy)``: *metrics* with each metric of *summary*
    at the value *policies* (a :class:`SchemaPolicies`) picks, and
    ``{metric: policy}`` of each value the run's own definition picked
    unlike the schema (plan 32 decision 1: the override is shown) — a value
    following the schema is not listed. A min/max/mean policy without a
    finite value leaves the metric out (plan 32 rule 3: missing, never its
    last value). Only a metric logged more than once can differ from its
    last value, so the rest are left as they are; *metrics* itself comes
    back when no value changes."""
    if not summary or not (run_defs or policies):
        return metrics, {}
    picked, overrides, dropped = {}, {}, []
    for name, seen in summary.items():
        column = policies.column(name)
        policy = policies.of(name, run_defs)
        value = seen[policy]
        if value is None:
            if name in metrics:
                dropped.append(name)
            continue
        if policy != column:
            overrides[name] = policy
        if not same_value(value, metrics.get(name)):
            picked[name] = value
    return _changed(metrics, picked, dropped), overrides


def _changed(metrics, picked, dropped):
    """*metrics* with *picked* set and *dropped* left out; itself when neither."""
    if not (picked or dropped):
        return metrics
    out = {**metrics, **picked}
    for name in dropped:
        del out[name]
    return out


def policy_of(row, name):
    """The summary policy *row*'s run picked for *name* unlike the schema, or None."""
    policy = row.get("metric_policy")
    return policy.get(name) if policy else None


def value_policy(overrides, name, policies):
    """The summary policy behind *name*'s value: its run's override in
    *overrides* (a row's ``metric_policy``), else *policies*' (a
    :class:`SchemaPolicies`) — None for ``last``."""
    policy = (overrides or {}).get(name) or policies.column(name)
    return None if policy == "last" else policy


def count_policy(counts, policy, by):
    """*counts* ``{policy: rows}`` moved by *by* rows of *policy* (None: no
    override, not counted); a count reaching 0 is dropped."""
    if policy:
        count = counts.get(policy, 0) + by
        if count:
            counts[policy] = count
        else:
            counts.pop(policy, None)


def policy_mix(counts):
    """``{"mixed": True, "policies": {policy: rows}}`` of an aggregate whose
    rows' runs override the schema's policy (*counts*, see
    :func:`count_policy`; the other rows follow the schema); ``{}`` without one."""
    return {"mixed": True, "policies": dict(counts)} if counts else {}

