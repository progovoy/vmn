#!/usr/bin/env python3
"""The units a job's chosen aggregate reads one value from (plan 31 §2),
and that value.

``job_agg_by=field:<params.k|tags.k>`` (and ``kind:<v>``, a ``tags.kind``
match) makes a job's units the nearest runs below it carrying the field, one
per branch. Which runs carry it is kept per parent as a :class:`UnitTally`
(``{(verstr, key, own value): rows}`` of the parent's direct children
carrying it), the way :class:`~vmn_exp.ui.job_rollup.StaticRollups` keeps any
tally: per base, moved across generations by the cache's deltas, a live
overlay per time bucket. The field is the unit's own, so a change to it is a
delta of the unit itself. A removal never loses anything (nothing is an
extreme), so these tallies are never rebuilt. Finding a job's units walks
only the jobs above a tally (:func:`carriers_below`), never its leaf rows;
a carrier under another one is a unit only with ``nested`` (plan 36 §2),
else it is skipped and counted.

A unit's value (:class:`UnitValue`) is its own metric (``own``, no
fallback: missing is missing) or the best over it and its subtree
(``best``), read off the schema rollups' per-parent extremes.
"""

from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.job_tally import _move
from vmn_exp.ui.leaderboard_group_fields import key_of, value_of

FIELD, KIND = "field:", "kind:"
KIND_FIELD = "tags.kind"


def own_value(row, metric):
    """*row*'s own *metric* when finite, else None."""
    value = (row.get("metrics") or {}).get(metric)
    return value if is_finite_number(value) else None


class UnitSpec:
    """Which children a :class:`UnitTally` keeps: those carrying *field*
    (with *wanted*, those whose value is it), each with its own *metric*."""

    def __init__(self, field, wanted, metric):
        self.field, self.wanted, self.metric = field, wanted, metric
        self._value, self._key = value_of(field), key_of(field)

    @classmethod
    def of(cls, by, metric):
        """The spec of a ``field:``/``kind:`` *by*."""
        if by.startswith(KIND):
            return cls(KIND_FIELD, by[len(KIND):], metric)
        return cls(by[len(FIELD):], None, metric)

    def unit_key(self, row):
        """*row*'s unit key, None when it is no unit (a ``kind:`` unit is its own key)."""
        value = self._value(row)
        if value is None or (self.wanted is not None and str(value) != self.wanted):
            return None
        return row["verstr"] if self.wanted is not None else self._key(row)

    def tally(self):
        return UnitTally()


class UnitTally:
    """A parent's direct children carrying the unit field."""

    __slots__ = ("units",)

    def __init__(self):
        self.units = {}  # {(verstr, key, own value): rows}

    def copy(self):
        out = UnitTally()
        out.units = dict(self.units)
        return out

    def empty(self):
        return not self.units

    def add(self, row, spec, by=1):
        key = spec.unit_key(row)
        if key is not None:
            _move(self.units, (row["verstr"], key, own_value(row, spec.metric)), by)
        return False


def carriers_below(job, tree, sources, nested=False, above=None):
    """``(units, skipped)``, each ``[(verstr, key, own value)]``: the runs
    below *job* carrying the field, from the per-parent tallies in
    *sources*, walking down the (unarchived) jobs on the way to a tally
    (*above*: :func:`jobs_above`). The nearest carrier on each branch is a
    unit; one under another carrier is a unit too when *nested* (plan 36
    §2), else it is skipped."""
    above = jobs_above(tree, sources) if above is None else above
    units, skipped = [], []
    stack, seen = [(job, False)], {job}
    while stack:
        parent, under = stack.pop()
        found = {}
        for tallies in sources:
            if parent in tallies:
                found.update(dict.fromkeys(tallies[parent].units))
        (skipped if under and not nested else units).extend(found)
        carrying = {unit[0] for unit in found}
        for kid in tree.nested.get(parent, ()):
            if kid in above and kid not in seen and kid not in tree.archived:
                seen.add(kid)
                stack.append((kid, under or kid in carrying))
    return units, skipped


def jobs_above(tree, sources):
    """The jobs holding a tally of *sources* and every job above them: the
    only ones a walk down to a carrier passes."""
    above = set()
    for tallies in sources:
        for parent in tallies:
            while parent is not None and parent not in above:
                above.add(parent)
                parent = tree.parent(parent)
    return above


class UnitValue:
    """``value(verstr, own)`` of a unit for *source*: ``own`` its own
    metric, ``best`` the best (by *up*) over it and the metric tallies of
    its subtree (*parts(job)*, for a job of *jobs*). Without a goal only a
    lone value (a leaf's own) is its best: more have no direction to rank."""

    def __init__(self, source, metric, up, parts, jobs):
        self.source, self.metric, self.up = source, metric, up
        self._parts, self._jobs = parts, jobs

    def __call__(self, verstr, own):
        if self.source == "own" or verstr not in self._jobs:
            return own  # a leaf's best is its own value
        below = self._below(verstr)
        if self.up is None:
            return None if below else own  # values to rank, no direction
        values = [(m.high if self.up else m.low)[0][0] for m in below]
        values += [] if own is None else [own]
        return (max if self.up else min)(values) if values else None

    def _below(self, verstr):
        """The metric tallies of job *verstr*'s subtree."""
        tallies = (part.metrics.get(self.metric) for part in self._parts(verstr))
        return [metric for metric in tallies if metric is not None]

    def of_row(self, row):
        """The value of the unit whose row is *row*."""
        return self(row["verstr"], own_value(row, self.metric))
