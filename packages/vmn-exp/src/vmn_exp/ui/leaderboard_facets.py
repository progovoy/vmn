#!/usr/bin/env python3
"""An app's filter vocabulary (branches, metric and param keys), once per
snapshot and moved on from the app's previous one.

:func:`~vmn_exp.ui.readers.experiments.facets` scans every row. Here each
snapshot's answer is kept as per-key row counts, so the next generation's
is the last one's counts minus the rows that left plus the rows that joined
(found by identity, :func:`~vmn_exp.ui.leaderboard_delta.changed_slots`).
"""
import threading

from vmn_exp.ui.leaderboard_delta import changed_slots, delta_limit, left_rows
from vmn_exp.ui.memo import LRU


def visible(rows, archived):
    return rows if archived else [row for row in rows if not row.get("archived")]


def _tally(counts, keys, by):
    for key in keys:
        count = counts.get(key, 0) + by
        if count:
            counts[key] = count
        else:
            counts.pop(key, None)


class FacetCounts:
    """How many rows carry each branch, metric key and param key."""

    def __init__(self, branches=None, metric_keys=None, param_keys=None, total=0):
        self.branches = branches or {}
        self.metric_keys = metric_keys or {}
        self.param_keys = param_keys or {}
        self.total = total

    @classmethod
    def of(cls, rows):
        return cls().moved((), rows)

    def moved(self, left, joined):
        """A copy without the *left* rows' contributions, with the *joined*'."""
        out = FacetCounts(
            dict(self.branches), dict(self.metric_keys), dict(self.param_keys),
            self.total + len(joined) - len(left),
        )
        for rows, by in ((left, -1), (joined, 1)):
            for row in rows:
                if row.get("branch"):
                    _tally(out.branches, [str(row["branch"])], by)
                _tally(out.metric_keys, row.get("metrics") or {}, by)
                _tally(out.param_keys, row.get("params") or {}, by)
        return out

    def payload(self):
        """What :func:`~vmn_exp.ui.readers.experiments.facets` answers."""
        return {
            "branches": sorted(self.branches),
            "metric_keys": sorted(self.metric_keys),
            "param_keys": sorted(self.param_keys),
            "total": self.total,
        }


class Facets:
    """Facet payloads per snapshot; counts carried per ``(app, archived)``."""

    def __init__(self, size=8):
        self._payloads = LRU(size)
        self._counts = {}  # {(app, archived): (snapshot, FacetCounts)}, the latest
        self._lock = threading.Lock()

    def get(self, snapshot, archived=False):
        archived = bool(archived)
        return self._payloads.per_snapshot(
            snapshot, lambda: self._counted(snapshot, archived).payload(), key=(archived,)
        )

    def _counted(self, snapshot, archived):
        key, rows = (snapshot.app_name, archived), snapshot.rows
        with self._lock:
            prev = self._counts.get(key)
        slots = prev and changed_slots(rows, prev[0].rows, delta_limit(rows))
        if slots is None:
            counts = FacetCounts.of(visible(rows, archived))
        else:
            left = visible(left_rows(rows, prev[0].rows, slots), archived)
            counts = prev[1].moved(left, visible([rows[i] for i in slots], archived))
        with self._lock:
            self._counts[key] = (snapshot, counts)
        return counts
