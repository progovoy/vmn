#!/usr/bin/env python3
"""``live_below`` (plan 28 §4.5): how many runs below a row still run, wait
or are stuck — its Jobs view rollup's counts (settled runs left out; 0 for
a run without children) — and ``running_below``/``stuck_below``, those
running or stuck alone (the outer runs' status chips): the core's
:mod:`~vmn_exp.core.query_below` counts, which ``vmn-exp list --query`` and
the SDK read, taken here from the cached rollups (:func:`board_extra`). A
``query`` or ``top_query`` reading one (the Live/Review presets, a status
chip) is judged on the order without it, per base and time bucket, not in
the cache's moved orders: a run deep in a tree changes it without changing
the row.
"""
from functools import cache as once

from vmn_exp.core.query import BELOW_FIELDS, filter_rows, query_roots
from vmn_exp.core.query_below import BELOW_STATES
from vmn_exp.core.query_extra import lean_extra
from vmn_exp.ui.job_tally import STATES
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.experiments import sort_rows

# Each of the BELOW_FIELDS and the rollup states it counts.
BELOW = {field: tuple(STATES[s] for s in states) for field, states in BELOW_STATES.items()}


def reads_below(query):
    return bool(query and query.strip()) and not BELOW_FIELDS.isdisjoint(query_roots(query))


def filters_read_below(f):
    """Whether the :class:`~vmn_exp.ui.leaderboard_scope.Filters` *f*'s
    ``query`` or ``top_query`` reads the :data:`BELOW` fields."""
    return reads_below(f.query) or reads_below(f.top_query)


def without_below(f):
    """*f* without its ``query``/``top_query`` reading the :data:`BELOW` fields."""
    return f._replace(query=None if reads_below(f.query) else f.query, top_query=None)


def _counter(summaries, states):
    def count(verstr):
        counts = (summaries().get(verstr) or {}).get("counts") or {}
        return sum(counts.get(state, 0) for state in states)
    return count


def board_extra(cache, snapshot, schema):
    """:func:`~vmn_exp.core.query_extra.lean_extra` of *snapshot* with the
    :data:`BELOW` fields read from *cache*'s job rollups (on the first read)."""
    summaries = once(lambda: cache.job_rollups(snapshot, schema))
    extra = dict(lean_extra(snapshot) or {})
    extra.update({field: _counter(summaries, states) for field, states in BELOW.items()})
    return extra


def passing(rows, f, extra):
    """Those of *rows* passing *f*'s ``top_query`` and ``query`` reading *extra*."""
    for query in (f.top_query, f.query if reads_below(f.query) else None):
        rows = filter_rows(rows, query, extra=extra)
    return rows


class LiveBelow:
    def __init__(self, cache, size=32):
        self._cache = cache
        self._orders = cache.generations.track(LRU(size))

    def ordered(self, snapshot, schema, last, f):
        """``cache._ordered`` for the Filters *f* reading the :data:`BELOW` fields."""
        cache = self._cache
        base, bucket = cache._base(snapshot)
        key = (base.token, bucket, cache.schema_key(schema), last) + f
        return self._orders.get(key, lambda: self._passing(snapshot, schema, last, f))

    def _passing(self, snapshot, schema, last, f):
        cache, plain = self._cache, without_below(f)
        extra = board_extra(cache, snapshot, schema)
        if not last:
            return passing(cache._ordered(snapshot, schema, None, plain), f, extra)
        base, bucket = cache._base(snapshot)
        rows = passing(base.tail(bucket, 0, plain), f, extra)
        return sort_rows(rows, schema, sort=f.sort, last=last, order=f.order)
