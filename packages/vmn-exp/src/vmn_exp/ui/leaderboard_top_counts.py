#!/usr/bin/env python3
"""How many top-level runs are jobs and how many single runs (plan 23 S7),
for the facets' ``jobs``/``singles``: per base, the static rows' counts
moved on from the app's last ones by the cache's deltas (the rows a time
bucket changes keep their tree fields, so they are counted from the base)."""

from vmn_exp.core.traced_lock import TracedLock
from vmn_exp.ui.leaderboard_facets import visible
from vmn_exp.ui.leaderboard_scope import JOBS, is_top
from vmn_exp.ui.memo import LRU


def top_counts(rows):
    """``{"jobs", "singles"}`` among *rows*' top-level runs."""
    jobs = singles = 0
    for row in rows:
        if is_top(row, True):
            if is_top(row, JOBS):
                jobs += 1
            else:
                singles += 1
    return {"jobs": jobs, "singles": singles}


def _plus(a, b, by=1):
    return {k: a[k] + by * b[k] for k in a}


class TopCounts:
    def __init__(self, cache, size=8):
        self._cache = cache
        self._answers = cache.generations.track(LRU(size))
        self._latest = {}  # {(app, archived): (base token, static counts)}
        self._lock = TracedLock("leaderboard top counts")

    def get(self, snapshot, archived):
        base = self._cache._base(snapshot)[0]
        return self._answers.get((base.token, archived), lambda: self._counted(base, archived))

    def _counted(self, base, archived):
        key = (base.snapshot.app_name, archived)
        with self._lock:
            last = self._latest.get(key)
        moves = last and self._cache._deltas.since(last[0], base)
        if moves:
            left, joined = (top_counts(visible(rows, archived)) for rows in moves)
            static = _plus(_plus(last[1], joined), left, -1)
        else:
            changed = set(base.patch.changed)
            rows = [row for i, row in enumerate(base.rows) if i not in changed]
            static = top_counts(visible(rows, archived))
        with self._lock:
            self._latest[key] = (base.token, static)
        live = top_counts(visible([base.rows[i] for i in base.patch.changed], archived))
        return _plus(static, live)
