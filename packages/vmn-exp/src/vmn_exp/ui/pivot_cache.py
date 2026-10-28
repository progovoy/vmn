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
rest of the app goes through, and answers 304 to its own ETag meanwhile.
A rebuilt base makes new rows, so its pivots are built once more (an entry
holds its subtree's rows until then, hence few entries).
"""
import hashlib
import itertools
import os
from operator import is_

from vmn_exp.core.tree import ancestors
from vmn_exp.ui.leaderboard_scope import Filters, check_scope, scope_positions
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.pivot import build_pivot

# Settled pivots kept: a few launches' worth of a Review page's heatmaps.
SETTLED_PIVOTS = 16
# Settled pivots' ETags are per process, like the board's.
_NONCE = os.urandom(8).hex()


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
        self._serials = itertools.count(1)

    def etag(self, snapshot, schema, spec):
        """:meth:`pivot`'s ETag: a settled pivot's own, kept while it is,
        else the board's (index generation and time bucket)."""
        entry = self._settled_entry(snapshot, schema, spec)
        if entry is None:
            return self._cache.etag(snapshot, schema, route="pivot", spec=spec)
        return hashlib.blake2b(f"{_NONCE}:{entry[2]}".encode(), digest_size=16).hexdigest()

    def pivot(self, snapshot, schema, spec):
        """*spec*'s (:class:`~vmn_exp.ui.pivot.PivotSpec`) payload over
        *snapshot*. Raises ``QueryError`` on a bad query,
        :class:`~vmn_exp.ui.leaderboard_scope.UnknownScope` on an unknown scope."""
        entry = self._settled_entry(snapshot, schema, spec)
        if entry is not None:
            return entry[1]
        base, bucket = self._cache._base(snapshot)
        key = (base.token, bucket, self._cache.schema_key(schema)) + spec
        return self._memo.get(key, lambda: _build(snapshot, schema, spec, base, bucket))

    def _settled_entry(self, snapshot, schema, spec):
        """``(rows, payload, serial)`` of a settled *spec*, else None."""
        base, bucket = self._cache._base(snapshot)
        check_scope(base, spec.scope)
        if spec.scope is None or not _settled(base, spec.scope):
            return None
        rows = _subtree_rows(base, spec.scope)
        key = (snapshot.app_name, self._cache.schema_key(schema)) + spec
        return self._settled.get(
            key, lambda: (rows, _build(snapshot, schema, spec, base, bucket), next(self._serials)),
            valid=lambda hit: _same(hit[0], rows))


def _build(snapshot, schema, spec, base, bucket):
    f = Filters(status=spec.status, query=spec.query, archived=spec.archived, scope=spec.scope)
    return build_pivot(snapshot, base.tail(bucket, 0, f), spec, schema)
