#!/usr/bin/env python3
"""A chosen aggregate on the Outer runs row (plan 31 §2): ``rolled``.

A :class:`JobAgg` names it: ``agg`` (the group-by vocabulary, the tails
``best10``/``worst10`` following the metric's goal), ``by`` (the units:
``children``, ``field:<params.k|tags.k>`` — the nearest runs carrying it,
a duplicate value a counted conflict left out, a carrier under another one
skipped and counted apart (``nested_skipped``) —, ``kind:<tags.kind>``
or ``runs``, every run below from the merged sketches, ``approx``),
``value`` (each unit's subtree best or its ``own`` metric, no fallback),
``metric`` (default the board's main metric) and ``nested`` (carriers at
any depth are units, plan 35 §2). A metric without a declared
goal has no value (plan 32). The app's ``experiment.ui.job_aggregate`` is
the default, a URL's values override it (:func:`job_agg_of`).

``rolled`` is read off the schema rollups' per-parent tallies (a unit's
subtree best: the extremes of its subtree's tallies) and, for ``field:``/
``kind:``, the unit tallies of :mod:`~vmn_exp.ui.job_units`; memoized per
(base, live bucket, schema, aggregate) with no minute in the key, for the
top-level jobs only (a tree row keeps its own values).
"""
from bisect import bisect_left
from collections import Counter, namedtuple

from vmn_exp.core.app_settings import check_job_aggregate, job_aggregate_of
from vmn_exp.core.metric_summary import policy_mix
from vmn_exp.core.metric_schema import higher_is_better, metric_goal, with_resolved_goals
from vmn_exp.ui.job_rollup_cache import _SplitRollups
from vmn_exp.ui.job_rollup_payload import count_fields, metric_fields, policy_fields
from vmn_exp.ui.job_units import UnitSpec, UnitValue, carriers_below, jobs_above, own_value
from vmn_exp.ui.job_views import child_rows
from vmn_exp.ui.leaderboard_group_summary import TAILS, of_sorted, stats, tail_quantile
from vmn_exp.ui.memo import LRU

JobAgg = namedtuple("JobAgg", "agg by value metric nested",
                    defaults=("best", "children", "best", None, False))
CHILDREN, RUNS = "children", "runs"
ANSWERS = 64
# ``runs``: the merged sketch's quantile fields (:func:`metric_fields`).
_SKETCH = {0.5: "p50", 0.9: "p90", 0.1: "p10"}


def job_agg_of(ui, agg=None, by=None, value=None, metric=None, nested=None):
    """The :class:`JobAgg` of the app's ``experiment.ui`` *ui* with the
    given values over it; ValueError naming a bad one."""
    given = {k: v for k, v in dict(agg=agg, by=by, value=value, metric=metric,
                                   nested=nested).items() if v is not None}
    return JobAgg(**{**job_aggregate_of(ui), **check_job_aggregate(given, "job_agg")})


def board_job_agg(cache, snapshot):
    """The app's default :class:`JobAgg` (its ``experiment.ui.job_aggregate``)."""
    return job_agg_of(cache.conf_of(snapshot)[1])


def _quantile(agg, goal):
    """The quantile *agg* reads (median 0.5, a tail by *goal*), else None."""
    if agg == "median":
        return 0.5
    return tail_quantile(agg, goal) if agg in TAILS else None


def percentile(agg, goal):
    """A tail's percentile label (``p90``), else None."""
    q = tail_quantile(agg, goal) if agg in TAILS else None
    return None if q is None else f"p{round(q * 100)}"


def _carried(agg):
    """Whether *agg*'s units are the runs carrying a field (``field:``/``kind:``)."""
    return agg.by not in (CHILDREN, RUNS)


def _choice(agg, metric, goal):
    """What names *agg*: ``{agg, by, source, metric, goal, percentile}``,
    plus ``nested`` for carried units (plan 35 §2)."""
    out = {"agg": agg.agg, "by": agg.by, "source": agg.value, "metric": metric, "goal": goal,
           "percentile": percentile(agg.agg, goal)}
    return {**out, "nested": agg.nested} if _carried(agg) else out


def _payload(agg, metric, goal, **fields):
    out = {**_choice(agg, metric, goal), "value": None, "n": 0, "of": 0,
           "conflicts": 0, "verstr": None, "approx": False}
    if _carried(agg):
        out["nested_skipped"] = 0
    out.update(fields)
    return out


def _holder(ordered, agg, goal, value):
    """The verstr of the unit of sorted ``(value, verstr)`` *ordered*
    holding *agg*'s *value* (a quantile's lower neighbour), None for the
    mean and an interpolated quantile no unit holds."""
    if agg == "best":
        agg = goal
    if agg == "mean":
        return None
    if agg == "max":
        return ordered[bisect_left(ordered, (value,))][1]
    at = 0 if agg == "min" else int(_quantile(agg, goal) * (len(ordered) - 1))
    return ordered[at][1] if ordered[at][0] == value else None


def _valued(units, value):
    """``{unit key: [(verstr, value)]}`` of ``(verstr, key, own)`` *units*
    (a unit without a key is its own): a lone unit's *value(verstr, own)*;
    a conflict's units are left unvalued (None), never read."""
    keyed = {}
    for verstr, key, own in units:
        keyed.setdefault(verstr if key is None else key, []).append((verstr, own))
    return {key: [(kept[0][0], value(*kept[0]))] if len(kept) == 1 else
            [(verstr, None) for verstr, _ in kept] for key, kept in keyed.items()}


def _ordered(keyed):
    """The sorted ``(value, verstr)`` of *keyed*'s lone units with a value."""
    return sorted((kept[0][1], kept[0][0]) for kept in keyed.values()
                  if len(kept) == 1 and kept[0][1] is not None)


def _of_units(keyed, ordered, agg, goal):
    """``{value, n, of, conflicts, verstr}`` of *keyed* units (:func:`_valued`),
    *ordered* their :func:`_ordered`."""
    fields = {"n": len(ordered), "of": len(keyed),
              "conflicts": sum(1 for kept in keyed.values() if len(kept) > 1)}
    value = of_sorted([p[0] for p in ordered], agg, goal) if goal else None
    if value is not None:
        fields.update(value=value, verstr=_holder(ordered, agg, goal, value))
    return fields


def _of_runs(parts, metric, agg, goal):
    """``{value, n, of, verstr, approx}`` (plus ``mixed``/``policies``) over
    every run of *parts*: a quantile from the merged sketches (``approx``),
    the rest exact."""
    q = _quantile(agg, goal)
    fields = {"of": count_fields(parts)["total"], "approx": q is not None}
    # The extreme an exact agg reads is the best of that goal: its holder.
    extreme = {"best": goal, "min": "min", "max": "max"}.get(agg)
    found = metric_fields(parts, metric, extreme, bins=1, quantiles=q is not None)
    if found is None:
        return fields
    fields["n"] = found["n"]
    fields.update({k: found[k] for k in ("mixed", "policies") if k in found})
    if goal is not None:
        fields["value"] = found[agg if q is None else _SKETCH[q]]
        fields["verstr"] = found["best_verstr"]
    return fields


class Pool:
    """One aggregate's answer over a snapshot: each job's ``rolled`` and the
    pooled header of a group of jobs (plan 34 §1). Per job it keeps plain
    data only: its valued units, its runs' policy overrides and the keys of
    the carriers it skipped as nested (``runs``: its tallies), read once by
    *entry(job)*, dropped by :meth:`freeze`."""

    def __init__(self, agg, metric, goal, entry):
        self.agg, self.metric, self.goal = agg, metric, goal
        self._entry, self._jobs = entry, {}
        self.top = {}  # {top-level job: rolled}

    def rolled(self, job):
        if self.metric is not None and job not in self._jobs:
            self._jobs[job] = self._entry(job)
        return _payload(self.agg, self.metric, self.goal, **self._fields([job])[0])

    def choice(self):
        """The aggregate's name (:func:`_choice`): a grouped page's ``job_agg``."""
        return _choice(self.agg, self.metric, self.goal)

    def freeze(self):
        """Keep the jobs read so far, and nothing *entry* holds (base, tree, overlays)."""
        self._entry = None
        return self

    def pooled(self, jobs):
        """The header of *jobs* (the latest attempt first): their pooled
        units' ``rolled`` fields, every aggregate of their values and
        ``from_earlier``; a unit key the jobs share counts from the first
        job carrying it, a nested key from none counts as skipped. {} when
        no unit has a value."""
        fields, ordered, earlier = self._fields(jobs)
        if not fields.get("n"):
            return {}
        extra = {"from_earlier": 0} if ordered is None else {
            **stats([p[0] for p in ordered], self.goal), "from_earlier": earlier}
        return {**extra, **_payload(self.agg, self.metric, self.goal, **fields)}

    def _fields(self, jobs):
        """``(fields, ordered values, units from a later job)`` of *jobs*
        (latest first) pooled; ``runs`` orders no units (None)."""
        if self.metric is None:
            return {}, None, 0
        read = [self._jobs[job] for job in jobs]
        if self.agg.by == RUNS:
            parts = [part for tallies, _, _ in read for part in tallies]
            return _of_runs(parts, self.metric, self.agg.agg, self.goal), None, 0
        keyed, earlier = _latest_wins([units for units, _, _ in read])
        ordered = _ordered(keyed)
        overrides, skipped = Counter(), set()
        for _, policies, nested in read:
            overrides.update(policies)
            skipped.update(nested)
        fields = {**_of_units(keyed, ordered, self.agg.agg, self.goal), **policy_mix(overrides)}
        skipped.difference_update(keyed)
        if skipped:
            fields["nested_skipped"] = len(skipped)
        return fields, ordered, sum(1 for key in earlier if len(keyed[key]) == 1)


def _keys(units):
    """The unit keys of ``(verstr, key, own)`` *units* (:func:`_valued`'s)."""
    return {verstr if key is None else key for verstr, key, _ in units}


def _latest_wins(attempts):
    """``(keyed, earlier)``: the keyed units of *attempts* (latest first),
    each key from the first attempt carrying it, and the keys taken from a
    later one."""
    if len(attempts) == 1:
        return attempts[0], set()
    keyed, earlier = {}, set()
    for i, units in enumerate(attempts):
        for key, kept in units.items():
            if key not in keyed:
                keyed[key] = kept
                if i:
                    earlier.add(key)
    return keyed, earlier


class JobAggregates:
    """``rolled`` per top-level job, memoized per (base, bucket, schema, aggregate)."""

    def __init__(self, cache, size=32):
        self._cache = cache
        self._answers = cache.generations.track(LRU(ANSWERS, name="job aggregates"))
        self._units = _SplitRollups(cache, size, spec_of=lambda key: UnitSpec.of(*key))

    def rolled(self, snapshot, schema, agg=None):
        """``{top-level job: rolled}`` (*agg* None: the app's default)."""
        return self.pool(snapshot, schema, agg).top

    def pool(self, snapshot, schema, agg=None):
        """The memoized :class:`Pool` of *agg* (None: the app's default)
        over *snapshot*: the top-level jobs' ``rolled`` and what pools them."""
        agg = agg or board_job_agg(self._cache, snapshot)
        base, bucket = self._cache._base(snapshot)
        key = (base.token, bucket, self._cache.schema_key(schema), agg)
        return self._answers.get(key, lambda: self._all(snapshot, schema, agg))

    def one(self, snapshot, schema, verstr, agg=None):
        """*verstr*'s ``rolled`` (a job at any depth), None when it is not a job."""
        agg = agg or board_job_agg(self._cache, snapshot)
        base, bucket = self._cache._base(snapshot)
        tree = self._cache.jobs.tree(base)
        if verstr not in tree.jobs:
            return None
        key = (base.token, bucket, self._cache.schema_key(schema), agg, verstr)
        return self._answers.get(key, lambda: self._payload_of(snapshot, schema, agg).rolled(verstr))

    def value_of(self, snapshot, schema, agg=None):
        """The :class:`~vmn_exp.ui.job_units.UnitValue` of *agg*'s source
        (the app's default; ``of_row`` the value of a row, ``metric``/``up``
        what it reads): the shared value function baselines pair by."""
        agg = agg or board_job_agg(self._cache, snapshot)
        metric, goal, (_, tree, _, parts) = self._inputs(snapshot, schema, agg)
        return UnitValue(agg.value, metric, higher_is_better(goal), parts, tree.jobs)

    def _inputs(self, snapshot, schema, agg):
        """``(metric, goal, parts)``: a metric the schema rollups do not track
        (a glob's goal) gets rollups of the schema with its goal resolved."""
        jobs = self._cache.jobs
        spec = jobs.spec(snapshot, schema)
        metric = agg.metric or spec.main
        goal = metric_goal(schema, metric) if metric else None
        if goal and metric not in spec.metrics:
            schema = with_resolved_goals(schema, [metric])
        return metric, goal, jobs.parts(snapshot, schema)

    def _all(self, snapshot, schema, agg):
        pool = self._payload_of(snapshot, schema, agg)
        pool.top = {job: pool.rolled(job) for job in self._cache.jobs.tree(
            self._cache._base(snapshot)[0]).top}
        return pool.freeze()

    def _payload_of(self, snapshot, schema, agg):
        """The unfrozen :class:`Pool` of *agg* over *snapshot*."""
        metric, goal, (base, tree, _, parts) = self._inputs(snapshot, schema, agg)
        entry = None
        if metric is not None and agg.by == RUNS:
            entry = lambda job: (list(parts(job)), None, ())  # noqa: E731
        elif metric is not None:
            value = UnitValue(agg.value, metric, higher_is_better(goal), parts, tree.jobs)
            found = self._units_of(snapshot, base, tree, agg, metric)

            def entry(job):
                units, skipped = found(job)
                return (_valued(units, value),
                        policy_fields(parts(job), metric).get("policies") or {},
                        _keys(skipped))
        return Pool(agg, metric, goal, entry)

    def _units_of(self, snapshot, base, tree, agg, metric):
        """``job -> ([(verstr, key, own)], skipped)``: its units by *agg*'s
        ``by`` and the carriers it skips as nested."""
        bucket = self._cache._base(snapshot)[1]
        if agg.by == CHILDREN:
            patched = base.patched(bucket)
            return lambda job: ([(row["verstr"], None, own_value(row, metric))
                                 for row in child_rows(base, patched, job)], ())
        static, live = self._units.sources(snapshot.app_name, base, bucket, (agg.by, metric))
        sources = (static.tallies, live)
        above = jobs_above(tree, sources)
        return lambda job: carriers_below(job, tree, sources, agg.nested, above)
