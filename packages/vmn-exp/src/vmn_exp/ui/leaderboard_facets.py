#!/usr/bin/env python3
"""An app's filter and Group by vocabulary (branches, metric, param and tag
keys, distinct values per param, runs with a parent), once per snapshot and
moved on from the app's previous one.

:func:`~vmn_exp.ui.readers.experiments.facets` scans every row. Here each
snapshot's answer is kept as per-key row counts, so the next generation's
is the last one's counts minus the rows that left plus the rows that joined
(found by identity, :func:`~vmn_exp.ui.leaderboard_delta.changed_slots`).
"""

from vmn_exp.core.traced_lock import TracedLock
from vmn_exp.ui.facet_values import DISTINCT_CAP, ParamValues
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


__all__ = ["DISTINCT_CAP", "FacetCounts", "Facets", "visible"]


class FacetCounts:
    """How many rows carry each branch, metric, param and tag key, each
    param's values, and how many rows have a parent."""

    def __init__(self, branches=None, metric_keys=None, param_keys=None, total=0,
                 tag_keys=None, param_values=None, parented=0, folded_params=None):
        self.branches = branches or {}
        self.metric_keys = metric_keys or {}
        self.param_keys = param_keys or {}
        self.tag_keys = tag_keys or {}
        self.param_values = param_values or ParamValues()
        self.parented = parented
        self.folded_params = folded_params or {}  # metric names a row also has as a param
        self.total = total

    @classmethod
    def of(cls, rows):
        return cls().moved((), rows)

    def moved(self, left, joined):
        """A copy without the *left* rows' contributions, with the *joined*'."""
        out = FacetCounts(
            dict(self.branches), dict(self.metric_keys), dict(self.param_keys),
            self.total + len(joined) - len(left),
            dict(self.tag_keys), self.param_values.copy(), self.parented,
            dict(self.folded_params),
        )
        for rows, by in ((left, -1), (joined, 1)):
            for row in rows:
                if row.get("branch"):
                    _tally(out.branches, [str(row["branch"])], by)
                metrics = row.get("metrics") or {}
                _tally(out.metric_keys, metrics, by)
                params = row.get("params") or {}
                _tally(out.folded_params, [m for m in metrics if m in params], by)
                _tally(out.param_keys, params, by)
                out.param_values.move(params, by)
                _tally(out.tag_keys, row.get("tags") or {}, by)
                if row.get("parent"):
                    out.parented += by
        return out

    def payload(self):
        """What :func:`~vmn_exp.ui.readers.experiments.facets` answers."""
        return {
            "branches": sorted(self.branches),
            "metric_keys": sorted(self.metric_keys),
            "param_keys": sorted(self.param_keys),
            "tag_keys": sorted(self.tag_keys),
            "param_values": self.param_values.payload(self.param_keys),
            "parented": self.parented,
            "total": self.total,
        }


class Facets:
    """Facet payloads per snapshot; counts carried per ``(app, archived)``."""

    def __init__(self, size=8):
        self._payloads = LRU(size)
        self._counted_memo = LRU(size)
        self._counts = {}  # {(app, archived): (snapshot, FacetCounts)}, the latest
        self._lock = TracedLock("leaderboard facets")

    def get(self, snapshot, archived=False):
        archived = bool(archived)
        return self._payloads.per_snapshot(
            snapshot, lambda: self.counts(snapshot, archived).payload(), key=(archived,)
        )

    def counts(self, snapshot, archived=False):
        """*snapshot*'s :class:`FacetCounts`, once per snapshot."""
        archived = bool(archived)
        return self._counted_memo.per_snapshot(
            snapshot, lambda: self._counted(snapshot, archived), key=(archived,))

    def common_metrics(self, snapshot):
        """The metric names most visible rows carry, most first (ties by name),
        leaving out numeric params folded into ``metrics``."""
        counts = self.counts(snapshot)
        keys = {m: n for m, n in counts.metric_keys.items() if m not in counts.folded_params}
        return sorted(keys, key=lambda m: (-keys[m], m))

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
