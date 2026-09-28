#!/usr/bin/env python3
"""Patching live rows into a cached leaderboard order.

Between two index generations only live runs (no exit code yet) change as
time passes: their status fields, and the ``tree_status`` of every run above
them. :class:`LivePatch` names that *changed* set once per snapshot and rolls
the ancestors' ``tree_status`` up from a precomputed terminal part, so a new
time bucket costs O(changed) instead of re-annotating every row. A snapshot
built from scratch walks each affected subtree (:meth:`LivePatch.of_rows`);
one derived from the previous generation gets the terminal parts from the
children's status counts instead (:meth:`LivePatch.from_counts`).

Every ordering ``sort_rows`` produces is a total order on a per-row key (the
storage position breaks ties, as its stable sorts do), so :func:`order_key`
reproduces it and :class:`MergedRows` places the changed rows into the
cached order of the others by bisection: O(changed · log N) per bucket, and a
page slice costs O(page + changed).
"""
import bisect
from collections import Counter

from vmn_exp.core.log import (
    DATE_SORTS,
    IDX_SORT,
    _sortable,
    metric_sort_descending,
    primary_metric,
)
from vmn_exp.core.tree import (
    children_by_parent,
    rollup_status,
    subtree_verstrs,
)
from vmn_exp.ui.leaderboard_tree import parent_in


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
    """The rows of one snapshot a time bucket can change, and how.

    ``_rollups`` is ``{i: (terminal statuses, live rows)}`` for each changed
    row *i*: the statuses no time bucket changes in its subtree (only their
    rollup matters) and the live rows beneath it.
    """

    def __init__(self, live, changed, rollups):
        self.live = tuple(live)
        self.changed = tuple(changed)
        self._rollups = rollups

    @classmethod
    def of_rows(cls, rows, live, position):
        """Walks every subtree; any parent graph, cycles included."""
        live_set = set(live)
        parent_of = {r["verstr"]: r.get("parent") for r in rows if r.get("parent")}
        affected = {
            position[v]
            for i in live
            for v in _ancestors_and_self(rows[i]["verstr"], parent_of)
            if v in position
        }
        rollups = cls._terminal_parts(rows, affected, live_set, position)
        return cls(live, sorted(affected | live_set), rollups)

    @classmethod
    def from_counts(cls, rows, live, position, edges, child_statuses):
        """O(changed) from ``{parent: {tree_status: count}}`` of the children
        (:func:`~vmn_exp.ui.leaderboard_tree.tree_index`); a forest only."""
        live_set, affected = set(live), set()
        for i in live:
            cursor = i
            while cursor is not None and cursor not in affected:
                affected.add(cursor)
                parent = parent_in(edges, rows[cursor]["verstr"])
                cursor = position.get(parent)
        kids, rollups = {}, {}
        for i in sorted(affected, key=lambda i: rows[i]["depth"], reverse=True):
            row = rows[i]
            tally = dict(child_statuses.get(row["verstr"], {}))
            terminal, under = set(), [i] if i in live_set else []
            for kid in kids.get(i, ()):
                tally[rows[kid]["tree_status"]] -= 1
                terminal |= rollups[kid][0]
                under.extend(rollups[kid][1])
            terminal.update(s for s, n in tally.items() if n)
            if i not in live_set:
                terminal.add(row["status"])
            summary = rollup_status(terminal)
            rollups[i] = (frozenset([summary] if summary else ()), tuple(under))
            parent = position.get(parent_in(edges, row["verstr"]))
            if parent is not None:
                kids.setdefault(parent, []).append(i)
        return cls(live, sorted(affected), rollups)

    @staticmethod
    def _terminal_parts(rows, affected, live, position):
        """``{i: (terminal statuses of i's subtree, live rows in it)}``."""
        children_of = children_by_parent(rows)
        parts = {}
        for i in affected:
            members = [position[v] for v in subtree_verstrs(rows[i]["verstr"], children_of)
                       if v in position]
            kids = [position[v] for v in children_of.get(rows[i]["verstr"], []) if v in position]
            parts[i] = (
                frozenset(rows[m]["status"] for m in members if m not in live),
                tuple(m for m in members if m in live),
                Counter(rows[k]["status"] for k in kids if k not in live),
                tuple(k for k in kids if k in live),
            )
        return parts

    def rolled_up(self, rows, fresh):
        """The changed rows (storage order) with *fresh* ``{i: live row}``
        swapped in and their ancestors' ``tree_status`` and ``child_counts``
        rolled up again."""
        out = []
        for i in self.changed:
            row = fresh.get(i, rows[i])
            terminal, under, kids_done, kids_live = self._rollups[i]
            status = rollup_status(terminal | {fresh[j]["status"] for j in under})
            counts = dict(kids_done + Counter(fresh[k]["status"] for k in kids_live))
            if row["tree_status"] != status or row["child_counts"] != counts:
                row = {**row, "tree_status": status, "child_counts": counts}
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


def _date_value(field, newest_first):
    def value_of(row):
        stamp = row.get(field)
        if not stamp:
            return None
        return _Desc(stamp) if newest_first else stamp

    return value_of


def order_key(schema, sort, descending, metric_present, position):
    """``(key, ranked)``: the sort key ``sort_rows`` orders by, and whether it
    ranks by a metric (*metric_present*: some filtered row carries it)."""
    if sort in DATE_SORTS:
        return _ranked(_date_value(sort, descending is not False), position), False
    if sort == IDX_SORT:
        sign = 1 if descending is False else -1
        return (lambda row: sign * row["idx"]), False
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
