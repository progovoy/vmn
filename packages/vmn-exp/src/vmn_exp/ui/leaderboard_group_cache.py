#!/usr/bin/env python3
"""Groupings memoized per index snapshot and moved on across generations,
the way :class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache` keeps its
static orders: one :class:`~vmn_exp.ui.leaderboard_groups.Grouping` per
(snapshot, schema, group, aggregate, sort, filters), derived from the last
one served for the same arguments across the deltas since (else built from
the cache's static order), plus one view per time bucket while runs are live.
"""
from vmn_exp.ui.leaderboard_group_fields import DEFAULT_AGGREGATE
from vmn_exp.ui.leaderboard_groups import GroupSpec, Grouping, groups_payload
from vmn_exp.ui.memo import LRU

# Groupings moved on across generations, like the cache's latest orders.
LATEST_GROUPINGS = 32


class GroupCache:
    def __init__(self, cache, size=32):
        self._cache = cache
        self._static = LRU(size)
        self._views = LRU(size)
        self._latest = LRU(LATEST_GROUPINGS)

    def groups(self, snapshot, schema, group, sort=None, status=None, query=None,
               order=None, archived=False, agg=DEFAULT_AGGREGATE, offset=0, limit=None,
               rows_per_group=10, group_key=None, rows_filter=None):
        """K1's payload (see :func:`~vmn_exp.ui.leaderboard_groups.groups_payload`).
        Raises ValueError on an unknown field or aggregate, ``QueryError`` on
        a bad *query*, LookupError on an unknown *group_key*. *rows_filter*
        (rows -> rows) replaces *query*, uncached: a query reading comments."""
        if rows_filter is None:
            spec = GroupSpec(group, agg, schema, sort, order, status, query, archived)
            grouping = self.grouping(snapshot, schema, spec)
        else:
            spec = GroupSpec(group, agg, schema, sort, order, status, None, archived)
            grouping = self._filtered(snapshot, schema, spec, rows_filter)
        return groups_payload(grouping, offset or 0, limit, rows_per_group, group_key)

    def _filtered(self, snapshot, schema, spec, rows_filter):
        base, bucket = self._cache._base(snapshot)
        live = dict(zip(base.patch.changed, base.changed_at(bucket)))
        sort, status, _, order, archived = spec.flat
        rows = rows_filter(self._cache.ordered(snapshot, schema, sort, status, order, archived))
        return Grouping.of_rows(base, spec, rows, live)

    def grouping(self, snapshot, schema, spec):
        cache = self._cache
        base, bucket = cache._base(snapshot)
        key = (cache.schema_key(schema), spec.group, spec.agg) + spec.flat
        static = self._static.get(
            (base.token,) + key, lambda: self._static_of(base, key, schema, spec))
        if not base.patch.changed:
            return static
        return self._views.get((base.token, bucket) + key, lambda: static.merged(base, bucket))

    def _static_of(self, base, key, schema, spec):
        last = self._latest.peek(key)
        moves = last and self._cache._deltas.since(last.token, base)
        grouping = moves and last.advanced(base, *moves)
        if not grouping:
            order = self._cache.static_order(base, schema, spec.flat)
            grouping = Grouping.build(base, spec, order)
        self._latest.put(key, grouping)
        return grouping

