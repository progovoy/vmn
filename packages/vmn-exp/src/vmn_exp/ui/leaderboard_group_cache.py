#!/usr/bin/env python3
"""Groupings memoized per index snapshot and moved on across generations,
the way :class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache` keeps its
static orders: one :class:`~vmn_exp.ui.leaderboard_groups.Grouping` per
(snapshot, schema, group, aggregate, sort, filters), derived from the last
one served for the same arguments across the deltas since (else built from
the cache's static order), plus one view per time bucket while runs are live.
"""
from vmn_exp.core.query import filter_rows
from vmn_exp.ui.leaderboard_group_fields import DEFAULT_AGGREGATE
from vmn_exp.ui.leaderboard_group_jobs import job_fields
from vmn_exp.ui.leaderboard_group_spec import GroupSpec
from vmn_exp.ui.leaderboard_groups import Grouping, groups_payload
from vmn_exp.ui.leaderboard_jobs import check_job_sort
from vmn_exp.ui.leaderboard_live_below import board_extra, reads_below
from vmn_exp.ui.leaderboard_scope import check_scope
from vmn_exp.ui.memo import LRU

# Groupings moved on across generations, like the cache's latest orders.
LATEST_GROUPINGS = 32


class GroupCache:
    def __init__(self, cache, size=32):
        self._cache = cache
        self._static = cache.generations.track(LRU(size))
        self._views = cache.generations.track(LRU(size))
        self._latest = LRU(LATEST_GROUPINGS)

    def groups(self, snapshot, schema, group, sort=None, status=None, query=None,
               order=None, archived=False, agg=DEFAULT_AGGREGATE, offset=0, limit=None,
               rows_per_group=10, group_key=None, rows_filter=None, scope=None, top=False,
               top_query=None):
        """K1's payload (see :func:`~vmn_exp.ui.leaderboard_groups.groups_payload`).
        Raises ValueError on an unknown field or aggregate, ``QueryError`` on
        a bad *query*, LookupError on an unknown *group_key* or *scope*.
        *rows_filter* (rows -> rows) replaces *query*, uncached: a query
        reading comments. *scope*/*top*/*top_query* narrow the rows as for a page; with
        *top* each group sums its jobs' rollups (plan 23 S7,
        :mod:`~vmn_exp.ui.leaderboard_group_jobs`). A *top_query* reading
        ``live_below`` groups uncached too (the top rows are few), as does a
        *query* reading one."""
        check_job_sort(sort, False)
        check_scope(self._cache._base(snapshot)[0], scope)
        if top_query and not top:
            raise ValueError("top_q needs top=1")
        where = dict(scope=scope, top=top, top_query=top_query)
        live_below = reads_below(top_query) or reads_below(query)
        if live_below and rows_filter is None:
            below = board_extra(self._cache, snapshot, schema)
            rows_filter = lambda rows: filter_rows(rows, query, extra=below)  # noqa: E731
        if rows_filter is None:
            spec = GroupSpec(group, agg, schema, sort, order, status, query, archived, **where)
            grouping = self.grouping(snapshot, schema, spec)
        else:
            spec = GroupSpec(group, agg, schema, sort, order, status, None, archived, **where)
            grouping = self._uncached(snapshot, schema, spec, rows_filter)
        unfiltered = None
        if status or query or rows_filter is not None:
            plain = GroupSpec(group, DEFAULT_AGGREGATE, schema, archived=archived, **where)
            unfiltered = (self._uncached(snapshot, schema, plain, list) if live_below
                          else self.grouping(snapshot, schema, plain))
        extra = job_fields(grouping, self._cache.job_rollups(snapshot, schema)) if top else None
        return groups_payload(grouping, offset or 0, limit, rows_per_group, group_key,
                              unfiltered, extra)

    def _uncached(self, snapshot, schema, spec, rows_filter):
        base, bucket = self._cache._base(snapshot)
        live = base.patched(bucket)
        f = spec.flat
        rows = rows_filter(self._cache.ordered(snapshot, schema, f.sort, f.status, f.order,
                                               f.archived, f.scope, f.top, top_query=f.top_query))
        return Grouping.of_rows(base, spec, rows, live)

    def grouping(self, snapshot, schema, spec):
        cache = self._cache
        base, bucket = cache._base(snapshot)
        key = (cache.schema_key(schema), spec.group, spec.agg, spec.group_sort) + spec.flat
        static = self._static.get(
            (base.token,) + key, lambda: self._static_of(base, key, schema, spec))
        if not base.patch.changed:
            return static
        return self._views.get((base.token, bucket) + key, lambda: static.merged(base, bucket))

    def _static_of(self, base, key, schema, spec):
        last = self._latest.peek(key)
        moves = last and self._cache._deltas.since(last.token, base, spec.reads_up)
        grouping = moves and last.advanced(base, *moves)
        if not grouping:
            order = self._cache.static_order(base, schema, spec.flat)
            grouping = Grouping.build(base, spec, order)
        self._latest.put(key, grouping)
        return grouping

