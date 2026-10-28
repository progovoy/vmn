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
rows like any changed row (outside the delta limit:
:func:`~vmn_exp.ui.leaderboard_delta.static_moves`). The median is the
value at P3's rank (``round((n - 1) / 2)``) as its sketches report it, a
bucket's value 1 % apart (:func:`~vmn_exp.ui.quantile_sketch.bucketed`), so
a large group's median, and its members' rows, rarely change.
"""
import bisect

from vmn_exp.core.status import RUNNING
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.job_split import check_split
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


def _parent(row):
    parent = row.get("parent")
    return parent if parent and parent != row["verstr"] else None


class SiblingDurations:
    """``{(parent, split key): sorted durations}`` of the finished siblings."""

    def __init__(self, split, durations):
        self.split = split
        self._key_of = key_of(check_split(split)) if split else None
        self.durations = durations
        self._medians = {}

    @classmethod
    def stamping(cls, rows, split):
        """Built from *rows*, each row's ratio set in place (rows the caller owns)."""
        out, durations, rated = cls(split, {}), {}, []
        for row in rows:
            finished = _finished(row)
            if not (finished or _rated(row)):
                row[FIELD] = None
                continue
            group = out.group(row)
            rated.append((row, group))
            if finished and group is not None and not row.get("archived"):
                durations.setdefault(group, []).append(row["duration_sec"])
        for values in durations.values():
            values.sort()
        out.durations = durations
        for row, group in rated:
            row[FIELD] = out._ratio(row["duration_sec"], group)
        return out

    def group(self, row):
        """*row*'s ``(parent, split key)``, or None without a parent."""
        parent = _parent(row)
        if parent is None:
            return None
        return parent, self._key_of(row) if self._key_of else None

    def _move(self, row, by, owned):
        """Adds (*by* -1: removes) *row*'s duration; its group, if counted."""
        if row.get("archived") or not _finished(row):
            return None
        group = self.group(row)
        if group is None:
            return None
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

    def _ratio(self, duration, group):
        median = self.median(group) if group is not None else None
        return round(duration / median, 3) if median and median > 0 else None

    def ratio(self, row):
        """*row*'s ``duration_ratio``, or None."""
        return self._ratio(row["duration_sec"], self.group(row)) if _rated(row) else None

    def advanced(self, old_rows, new_rows):
        """``(moved, groups whose median changed)``: these durations without
        the *old_rows*', with the *new_rows*'."""
        out, owned, touched = SiblingDurations(self.split, dict(self.durations)), set(), set()
        for rows, by in ((old_rows, -1), (new_rows, 1)):
            for row in rows:
                touched.add(out._move(row, by, owned))
        touched.discard(None)
        return out, {g for g in touched if self.median(g) != out.median(g)}


def stamped(rows, siblings):
    """Sets every row's ratio in place (rows the caller owns)."""
    for row in rows:
        row[FIELD] = siblings.ratio(row)


def restamped(base_parts, siblings, changed, fresh, rebuilt):
    """Sets the ratio of the *fresh* rows (in place) and of every member of
    the *changed* groups: a row not in *rebuilt* (an older generation's
    object) is replaced by a copy and named in *rebuilt*; the verstrs so
    copied are returned. *base_parts* is ``(rows, position, children_of)``
    of the new base."""
    rows, position, children_of = base_parts
    copied = set()
    for row in fresh.values():
        row[FIELD] = siblings.ratio(row)
    for parent, key in changed:
        for kid in children_of.get(parent, ()):
            at = position.get(kid)
            row = rows[at] if at is not None else None
            if row is None or kid in fresh or siblings.group(row) != (parent, key):
                continue
            ratio = siblings.ratio(row)
            if kid in rebuilt:
                row[FIELD] = ratio
            elif row.get(FIELD) != ratio:
                rows[at] = {**row, FIELD: ratio}
                copied.add(kid)
    rebuilt |= copied
    return copied
