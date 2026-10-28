#!/usr/bin/env python3
"""A board row's ``duration_ratio`` (plan 28 N4): its ``duration_sec`` over
the median duration of its siblings — the finished (succeeded or failed),
unarchived runs under the same parent with the same value of the app's
split field (``experiment.ui.split_by``, P3's; none: the parent alone).
Durations are skewed, so a ratio to the median, not a z-score. A running
run's ratio uses its elapsed time (its row is restated per time bucket).
Fewer than :data:`MIN_SIBLINGS` finished siblings (the run counted) give
no ratio, as does a run with no parent, a waiting or stuck run, and one
that finished without an end time (their elapsed time means nothing).

The durations are kept sorted per (parent, split value), moved by the rows
a new index generation changed (:meth:`SiblingDurations.advanced`); a group
whose median then reads otherwise gets every member's ratio again
(:func:`restamped`), as new row objects, so the cached orders move those
rows like any changed row (exempt from their delta limit,
:func:`~vmn_exp.ui.leaderboard_delta.static_moves`). The median is the
value at P3's rank (``round((n - 1) / 2)``) as its sketches report it, a
bucket's value 1 % apart (:func:`~vmn_exp.ui.quantile_sketch.bucketed`), so
a large group's median, and its members' rows, rarely change.
"""
import bisect

from vmn_exp.core.children import parent_of
from vmn_exp.core.status import RUNNING
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.job_tally import DONE
from vmn_exp.ui.leaderboard_group_fields import key_of
from vmn_exp.ui.quantile_sketch import bucketed

FIELD = "duration_ratio"
MIN_SIBLINGS = 3


def _finished(row):
    """Whether *row* ran to an end it recorded (its duration is final)."""
    return (row.get("status") in DONE and bool(row.get("finished_at"))
            and is_finite_number(row.get("duration_sec")))


def _rated(row):
    """Whether *row* can have a ratio: finished, or running (elapsed time)."""
    return _finished(row) or (row.get("status") == RUNNING
                              and is_finite_number(row.get("duration_sec")))


def _counted(row):
    """Whether *row*'s duration counts toward its siblings' median."""
    return _finished(row) and not row.get("archived")


class SiblingDurations:
    """``{(parent, split key): sorted durations}`` of the finished siblings."""

    def __init__(self, split, durations):
        self.split = split
        self._key_of = key_of(split) if split else None
        self.durations = durations
        self._medians = {}

    @classmethod
    def stamping(cls, rows, split):
        """Built from *rows*, each row's ratio set in place (rows the caller owns)."""
        out = cls(split, {})
        for row in rows:
            group = out.group(row) if _counted(row) else None
            if group is not None:
                out.durations.setdefault(group, []).append(row["duration_sec"])
        for values in out.durations.values():
            values.sort()
        stamped(rows, out)
        return out

    def group(self, row):
        """*row*'s ``(parent, split key)``, or None without a parent."""
        parent = parent_of(row)
        if parent is None:
            return None
        return parent, self._key_of(row) if self._key_of else None

    def _move(self, row, by, owned):
        """Adds (*by* -1: removes) *row*'s counted duration in its *group*."""
        group = self.group(row)
        if group not in owned:
            owned.add(group)
            self.durations[group] = list(self.durations.get(group, ()))
        values, duration = self.durations[group], row["duration_sec"]
        if by > 0:
            bisect.insort(values, duration)
        else:
            del values[bisect.bisect_left(values, duration)]
        if not values:
            del self.durations[group]
            owned.discard(group)
        return group

    def median(self, group):
        if group not in self._medians:
            values = self.durations.get(group, ())
            enough = len(values) >= MIN_SIBLINGS
            self._medians[group] = bucketed(values[round((len(values) - 1) / 2)]) if enough else None
        return self._medians[group]

    def ratio(self, row, group=None):
        """*row*'s ``duration_ratio`` (*group*: its :meth:`group`, when known), or None."""
        if not _rated(row):
            return None
        median = self.median(group or self.group(row))
        return round(row["duration_sec"] / median, 3) if median and median > 0 else None

    def advanced(self, old_rows, new_rows):
        """``(moved, groups whose median changed)``: these durations without
        the *old_rows*', with the *new_rows*' (this one when none counts)."""
        moves = [(row, by) for rows, by in ((old_rows, -1), (new_rows, 1)) for row in rows
                 if _counted(row) and self.group(row) is not None]
        if not moves:
            return self, set()
        out, owned = SiblingDurations(self.split, dict(self.durations)), set()
        touched = {out._move(row, by, owned) for row, by in moves}
        return out, {g for g in touched if self.median(g) != out.median(g)}


def stamped(rows, siblings):
    """Sets every row's ratio in place (rows the caller owns)."""
    for row in rows:
        row[FIELD] = siblings.ratio(row)


def restamped(rows, position, children_of, siblings, changed, fresh, rebuilt):
    """Sets the ratio of the *fresh* rows (in place) and of every member of
    the *changed* groups of the new base's *rows*: one in *rebuilt* in
    place, an older generation's object as a copy; the verstrs copied."""
    stamped(fresh.values(), siblings)
    keys_of = {}
    for parent, key in changed:
        keys_of.setdefault(parent, set()).add(key)
    copied = set()
    for parent, keys in keys_of.items():
        for kid in children_of.get(parent, ()):
            at = position.get(kid)
            if at is None or kid in fresh:
                continue
            row, group = rows[at], siblings.group(rows[at])
            if group[1] not in keys:
                continue
            ratio = siblings.ratio(row, group)
            if kid in rebuilt:
                row[FIELD] = ratio
            elif row.get(FIELD) != ratio:
                rows[at] = {**row, FIELD: ratio}
                copied.add(kid)
    return copied
