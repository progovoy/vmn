#!/usr/bin/env python3
"""Pivots (:mod:`~vmn_exp.ui.pivot`) memoized per index snapshot and time
bucket, like the board's answers, and a settled outer run's pivots kept
across generations until its subtree changes (plan 28 N2).

An outer run is settled for a pivot when nothing live is under it, nor the
run itself (:mod:`~vmn_exp.ui.settled_subtree`): a finished launch's heatmap
is built once per process, however many generations the rest of the app
goes through, and answers 304 to its own ETag meanwhile.
A rebuilt base makes new rows, so its pivots are built once more (an entry
holds its subtree's rows until then, hence few entries).
"""
import hashlib
import itertools
import os

from vmn_exp.ui.leaderboard_scope import Filters, check_scope
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.pivot import build_pivot
from vmn_exp.ui.settled_subtree import same_rows, settled, subtree_rows

# Settled pivots kept: a few launches' worth of a Review page's heatmaps.
SETTLED_PIVOTS = 16
# Settled pivots' ETags are per process, like the board's.
_NONCE = os.urandom(8).hex()


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
        if spec.scope is None or not settled(base, spec.scope):
            return None
        rows = subtree_rows(base, spec.scope)
        key = (snapshot.app_name, self._cache.schema_key(schema)) + spec
        return self._settled.get(
            key, lambda: (rows, _build(snapshot, schema, spec, base, bucket), next(self._serials)),
            valid=lambda hit: same_rows(hit[0], rows))


def _build(snapshot, schema, spec, base, bucket):
    f = Filters(status=spec.status, query=spec.query, archived=spec.archived, scope=spec.scope)
    return build_pivot(snapshot, base.tail(bucket, 0, f), spec, schema)
