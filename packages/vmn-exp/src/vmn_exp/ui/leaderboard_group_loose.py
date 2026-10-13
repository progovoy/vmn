#!/usr/bin/env python3
"""The loose rows of a link grouping (plan 22 F12): grouped by ``parent``,
``forked_from`` or ``rerun_of``, the runs with no link are not a group. They
are the no-value group's rows less the runs that head a group of the same
grouping (those are shown as headers), so the payload's ``loose`` group holds
each run once.

Derived from a :class:`~vmn_exp.ui.leaderboard_groups.Grouping`'s state, so
it is as current as the grouping however that was moved on: each head is
found in the sorted no-value rows by its sort key, O(groups · log n).
"""
from vmn_exp.ui.leaderboard_group_fields import NONE, key_text


def _at(rows, i):
    return rows[i:i + 1][0]  # a MergedRows only slices


def _index(rows, row, key):
    """Where *row* sits in the sorted *rows*, or None when it is not there."""
    target, lo, hi = key(row), 0, len(rows)
    while lo < hi:
        mid = (lo + hi) // 2
        if key(_at(rows, mid)) < target:
            lo = mid + 1
        else:
            hi = mid
    if lo < len(rows) and _at(rows, lo)["verstr"] == row["verstr"]:
        return lo
    return None


class Loose:
    """The no-value rows of *grouping* that head none of its groups."""

    def __init__(self, grouping):
        rows = grouping.members[NONE]
        heads = {}
        for group in grouping.members:
            row = None if group == NONE else grouping.row_of(key_text(group))
            at = None if row is None else _index(rows, row, grouping.key)
            if at is not None:
                heads[at] = _at(rows, at)
        self._rows, self._skipped = rows, sorted(heads)
        summary = grouping.summaries[NONE]
        self.summary = summary.copy().remove(list(heads.values())) if heads else summary
        self.size = len(rows) - len(heads)

    def page(self, offset, limit):
        """The loose rows ``[offset:offset + limit]``."""
        start = offset
        for at in self._skipped:
            if at > start:
                break
            start += 1
        skipped = set(self._skipped)
        window = self._rows[start:start + limit + len(skipped)]
        out = [row for i, row in enumerate(window, start) if i not in skipped]
        return out[:limit]
