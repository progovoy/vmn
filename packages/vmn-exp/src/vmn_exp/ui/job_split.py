#!/usr/bin/env python3
"""A job rollup's counts and durations split by one tag or param (plan 28
P3): ``tags.kind`` keeps a refit backlog from hiding behind thousands of
done trials.

A parent's rows go to one :class:`SplitTallies`: a :class:`SplitTally` per
value for its :data:`MAX_VALUES` first values in key order (``named``), and
one for the rest (``other``) — so a parent holds at most 13 duration
sketches whatever the field's cardinality. Counts and sketches are exact
under removal; a removal that empties a named value while ``other`` holds
runs reports the tallies unknown (a value of ``other`` should take its
place), and the caller rebuilds them from the parent's rows, as it does for
a :class:`~vmn_exp.ui.job_tally.Tally`'s lost extreme.
"""
from vmn_exp.core.settle import counted_status
from vmn_exp.ui.job_tally import DONE, _move
from vmn_exp.ui.leaderboard_group_fields import is_dict_field, key_of, value_of
from vmn_exp.ui.quantile_sketch import QuantileSketch

MAX_VALUES = 12


def check_split(field):
    """*field* when it is a ``tags.<k>``/``params.<k>``, else ValueError."""
    if is_dict_field(field):
        return field
    raise ValueError(f"split must be tags.<key> or params.<key>, not {field!r}")


class SplitSpec:
    """The field a :class:`SplitTallies` splits rows by."""

    def __init__(self, field):
        self.field = check_split(field)
        self.key_of = key_of(field)

    def tally(self):
        return SplitTallies()


class SplitTally:
    """One value's status counts and duration sketch; *value* is a member
    row's raw value (its clause keeps the type)."""

    __slots__ = ("counts", "duration", "value")

    def __init__(self, value=None):
        self.counts, self.value = {}, value
        self.duration = QuantileSketch()

    @property
    def total(self):
        return sum(self.counts.values())

    def copy(self):
        out = SplitTally(self.value)
        out.counts, out.duration = dict(self.counts), self.duration.copy()
        return out

    def add(self, row, by=1):
        _move(self.counts, counted_status(row), by)
        if row.get("status") in DONE and row.get("finished_at"):
            self.duration.add(row.get("duration_sec"), by)

    def merge(self, other):
        for status, count in other.counts.items():
            _move(self.counts, status, count)
        self.duration.merge(other.duration)


class SplitTallies:
    """What a parent's rows add to every job above it, per value."""

    __slots__ = ("named", "other")

    def __init__(self):
        self.named, self.other = {}, SplitTally()

    def copy(self):
        out = SplitTallies()
        out.named = {key: tally.copy() for key, tally in self.named.items()}
        out.other = self.other.copy()
        return out

    def empty(self):
        return not self.named and not self.other.counts

    def cut(self):
        """The last named key while ``other`` holds runs (keys past it may
        be in ``other``), else None."""
        return max(self.named) if self.other.counts and self.named else None

    def add(self, row, spec, by=1):
        """Adds *row* (``by=-1``: removes it); whether the tallies are now unknown."""
        key = spec.key_of(row)
        tally = self.named.get(key)
        if tally is None and by > 0:
            tally = self._admit(key, value_of(spec.field)(row))
        if tally is None:
            tally = self.other
        tally.add(row, by)
        if tally is not self.other and not tally.counts:
            del self.named[key]
            return bool(self.other.counts)
        return False

    def _admit(self, key, value):
        """*key*'s new named tally, or None when it belongs under ``other``."""
        if len(self.named) >= MAX_VALUES:
            last = max(self.named)
            if key > last:
                return None
            self.other.merge(self.named.pop(last))
        tally = self.named[key] = SplitTally(value)
        return tally
