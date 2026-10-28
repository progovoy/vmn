#!/usr/bin/env python3
"""Pivots (:mod:`~vmn_exp.ui.pivot`) memoized per index snapshot and time
bucket, like the board's answers, and a settled outer run's pivots kept
across generations until its subtree changes (plan 28 N2).

An outer run is settled for a pivot when nothing live is under it, nor the
run itself: no time bucket changes its rows (the board's live patch holds
no row of the subtree, :mod:`~vmn_exp.ui.leaderboard_live`). A derived
generation keeps every unchanged row object, so the subtree is unchanged
while its rows, and the chain above it an ``up`` field reads, are the same
objects (an O(subtree) identity walk at C speed, no build): a finished
launch's heatmap is built once per process, however many generations the
rest of the app goes through. A rebuilt base makes new rows, so its pivots
are built once more.
"""
from operator import is_

from vmn_exp.core.tree import ancestors
from vmn_exp.ui.leaderboard_scope import Filters, check_scope, scope_positions
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.pivot import build_pivot

# Settled pivots kept: a few launches' worth of a Review page's heatmaps.
SETTLED_PIVOTS = 64


def _settled(base, scope):
    """Whether no time bucket changes *scope*'s subtree or *scope*."""
    at = base.position.get(scope)
    return at is not None and at not in base.patch.changed


def _subtree_rows(base, scope):
    """The rows of *scope*'s subtree, then *scope* and its ancestors'."""
    position, rows = base.position, base.rows
    chain = [scope] + ancestors(scope, base.snapshot.edges)
    return ([rows[i] for i in scope_positions(base, scope)]
            + [rows[position[v]] for v in chain if v in position])


def _same(kept, rows):
    return len(kept) == len(rows) and all(map(is_, kept, rows))


class PivotCache:
    def __init__(self, cache, size=32):
        self._cache = cache
        self._memo = cache.generations.track(LRU(size, name="pivots"))
        self._settled = LRU(SETTLED_PIVOTS, name="settled pivots")

    def pivot(self, snapshot, schema, spec):
        """*spec*'s (:class:`~vmn_exp.ui.pivot.PivotSpec`) payload over
        *snapshot*. Raises ``QueryError`` on a bad query,
        :class:`~vmn_exp.ui.leaderboard_scope.UnknownScope` on an unknown scope."""
        cache = self._cache
        base, bucket = cache._base(snapshot)
        check_scope(base, spec.scope)
        key = (cache.schema_key(schema),) + spec

        def build():
            f = Filters(status=spec.status, query=spec.query, archived=spec.archived,
                        scope=spec.scope)
            return build_pivot(snapshot, base.tail(bucket, 0, f), spec, schema)

        if spec.scope is not None and _settled(base, spec.scope):
            rows = _subtree_rows(base, spec.scope)
            return self._settled.get((snapshot.app_name,) + key, lambda: (rows, build()),
                                     valid=lambda hit: _same(hit[0], rows))[1]
        return self._memo.get((base.token, bucket) + key, build)
