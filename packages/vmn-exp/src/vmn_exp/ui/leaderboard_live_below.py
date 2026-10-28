#!/usr/bin/env python3
"""``live_below`` (plan 28 §4.5): how many runs below a top-level row still
run, wait or are stuck — its Jobs view rollup's counts (settled runs left
out; 0 for a single run). A ``top_query`` reading it (the Live/Review
presets) is judged on the order without it, per base and time bucket, not
in the cache's moved orders: a run deep in a tree changes it without
changing the top-level row.
"""
from vmn_exp.core.query import filter_rows, query_roots
from vmn_exp.core.query_extra import lean_extra
from vmn_exp.ui.memo import LRU

FIELD = "live_below"
LIVE_STATES = ("running", "waiting", "stuck")


def reads_live_below(query):
    return bool(query and query.strip()) and FIELD in query_roots(query)


def live_count(summary):
    counts = (summary or {}).get("counts") or {}
    return sum(counts.get(state, 0) for state in LIVE_STATES)


def passing(snapshot, rows, query, summaries):
    """Those of *rows* passing *query*, ``live_below`` read from *summaries*."""
    extra = dict(lean_extra(snapshot) or {})
    extra[FIELD] = lambda verstr: live_count(summaries.get(verstr))
    return filter_rows(rows, query, extra=extra)


class LiveBelow:
    def __init__(self, cache, size=32):
        self._cache = cache
        self._orders = cache.generations.track(LRU(size))

    def ordered(self, snapshot, schema, last, f):
        """``cache._ordered`` for the Filters *f* whose ``top_query`` reads ``live_below``."""
        cache = self._cache
        base, bucket = cache._base(snapshot)
        key = (base.token, bucket, cache.schema_key(schema), last) + f
        return self._orders.get(key, lambda: passing(
            snapshot, cache._ordered(snapshot, schema, last, f._replace(top_query=None)),
            f.top_query, cache.job_rollups(snapshot, schema)))
