#!/usr/bin/env python3
"""``live_below`` (plan 28 §4.5): how many runs below a top-level row still
run, wait or are stuck — its Jobs view rollup's counts (settled runs left
out; 0 for a single run) — and ``running_below``/``stuck_below``, those
running or stuck alone (the outer runs' status chips): the core's
:mod:`~vmn_exp.core.query_below` counts, which ``vmn-exp list --query`` and
the SDK read, taken here from the cached rollups. A ``top_query``
reading one (the Live/Review presets, a status chip) is judged on the order
without it, per base and time bucket, not in the cache's moved orders: a
run deep in a tree changes it without changing the top-level row.
"""
from vmn_exp.core.query import BELOW_FIELDS, filter_rows, query_roots
from vmn_exp.core.query_below import BELOW_STATES
from vmn_exp.core.query_extra import lean_extra
from vmn_exp.ui.job_tally import STATES
from vmn_exp.ui.memo import LRU

# Each of the BELOW_FIELDS and the rollup states it counts.
BELOW = {field: tuple(STATES[s] for s in states) for field, states in BELOW_STATES.items()}


def reads_below(query):
    return bool(query and query.strip()) and not BELOW_FIELDS.isdisjoint(query_roots(query))


def _counter(summaries, states):
    def count(verstr):
        counts = (summaries.get(verstr) or {}).get("counts") or {}
        return sum(counts.get(state, 0) for state in states)
    return count


def passing(snapshot, rows, query, summaries):
    """Those of *rows* passing *query*, the :data:`BELOW` fields read from *summaries*."""
    extra = dict(lean_extra(snapshot) or {})
    extra.update({field: _counter(summaries, states) for field, states in BELOW.items()})
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
