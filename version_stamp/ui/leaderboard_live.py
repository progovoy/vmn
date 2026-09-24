#!/usr/bin/env python3
"""Patching live rows into a cached leaderboard order.

Between two index generations only live runs (no exit code yet) change as
time passes: their status fields, and the ``tree_status`` of every run above
them. :class:`LivePatch` names that *changed* set once per snapshot and rolls
the ancestors' ``tree_status`` up from a precomputed terminal part, so a new
time bucket costs O(changed) instead of re-annotating every row.

Every ordering ``sort_rows`` produces is a total order on a per-row key (the
storage position breaks ties, as its stable sorts do), so :func:`order_key`
reproduces it and :class:`MergedRows` places the changed rows into the
cached order of the others by bisection: O(changed · log N) per bucket, and a
page slice costs O(page + changed).
"""
import bisect

from version_stamp.core.experiment_log import (
    TIMESTAMP_SORT,
    _sortable,
    metric_sort_descending,
    primary_metric,
)
from version_stamp.core.experiment_tree import (
    children_by_parent,
    rollup_status,
    subtree_verstrs,
)


def _ancestors_and_self(verstr, parent_of):
    """*verstr* and every run its parent chain reaches (cycle-safe)."""
    chain, cursor = [verstr], verstr
    seen = {verstr}
    while parent_of.get(cursor) and parent_of[cursor] not in seen:
        cursor = parent_of[cursor]
        chain.append(cursor)
        seen.add(cursor)
    return chain


class LivePatch:
    """The rows of one snapshot a time bucket can change, and how."""

    def __init__(self, rows, live, position):
        live_set = set(live)
        parent_of = {r["verstr"]: r.get("parent") for r in rows if r.get("parent")}
        affected = {
            position[v]
            for i in live
            for v in _ancestors_and_self(rows[i]["verstr"], parent_of)
            if v in position
        }
        self.live = tuple(live)
        self.changed = tuple(sorted(affected | live_set))
        self._rollups = self._terminal_parts(rows, affected, live_set, position)

    @staticmethod
    def _terminal_parts(rows, affected, live, position):
        """``{i: (terminal statuses of i's subtree, live rows in it)}``."""
        children_of = children_by_parent(rows)
        parts = {}
        for i in affected:
            members = [position[v] for v in subtree_verstrs(rows[i]["verstr"], children_of)
                       if v in position]
            parts[i] = (
                frozenset(rows[m]["status"] for m in members if m not in live),
                tuple(m for m in members if m in live),
            )
        return parts

    def rolled_up(self, rows, fresh):
        """The changed rows (storage order) with *fresh* ``{i: live row}``
        swapped in and their ancestors' ``tree_status`` rolled up again."""
        out = []
        for i in self.changed:
            row = fresh.get(i, rows[i])
            terminal, under = self._rollups[i]
            status = rollup_status(terminal | {fresh[j]["status"] for j in under})
            if row["tree_status"] != status:
                row = {**row, "tree_status": status}
            out.append(row)
        return out


class _Desc:
    """Reverses the order of a value inside a sort key."""

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __lt__(self, other):
        return other.value < self.value

    def __eq__(self, other):
        return self.value == other.value


def _ranked(value_of, position):
    """Rows with a value first, by it; the rest after; storage order breaks ties."""

    def key(row):
        value = value_of(row)
        if value is None:
            return (1, position[row["verstr"]])
        return (0, value, position[row["verstr"]])

    return key


def _metric_value(metric, descending):
    def value_of(row):
        value = row["metrics"].get(metric)
        if not _sortable(value):
            return None
        return -value if descending else value

    return value_of


def _timestamp_value(newest_first):
    def value_of(row):
        stamp = row.get("timestamp")
        if not stamp:
            return None
        return _Desc(stamp) if newest_first else stamp

    return value_of


def order_key(schema, sort, descending, metric_present, position):
    """``(key, ranked)``: the sort key ``sort_rows`` orders by, and whether it
    ranks by a metric (*metric_present*: some filtered row carries it)."""
    if sort == TIMESTAMP_SORT:
        return _ranked(_timestamp_value(descending is not False), position), False
    metric = sort or primary_metric(schema)
    if not metric or not metric_present(metric):
        sign = -1 if descending else 1
        return (lambda row: sign * position[row["verstr"]]), False
    if descending is None:
        descending = metric in (schema or {}) and metric_sort_descending(schema, metric)
    return _ranked(_metric_value(metric, descending), position), True


def _bisect(rows, target, key):
    lo, hi = 0, len(rows)
    while lo < hi:
        mid = (lo + hi) // 2
        if key(rows[mid]) < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


class MergedRows:
    """A read-only sequence: sorted *static* rows with sorted *live* rows
    placed among them by *key*, never materialized as one list."""

    def __init__(self, static, live, key):
        self._static = static
        self._live = live
        # Where each live row lands in the merged order.
        self._at = [_bisect(static, key(row), key) + j for j, row in enumerate(live)]

    def __len__(self):
        return len(self._static) + len(self._live)

    def __iter__(self):
        return iter(self[:])

    def __getitem__(self, span):
        start, stop, _ = span.indices(len(self))
        j = bisect.bisect_left(self._at, start)
        out, pos = [], start
        for at in self._at[j:]:
            if at >= stop:
                break
            # Static rows before position *pos* number pos - j.
            out.extend(self._static[pos - j : at - j])
            out.append(self._live[j])
            j, pos = j + 1, at + 1
        out.extend(self._static[pos - j : stop - j])
        return out
