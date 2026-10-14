#!/usr/bin/env python3
"""The Jobs view (plan 23 S2): the top-level rows (``top``), each carrying
``job``, its job's compact rollup (:mod:`~vmn_exp.ui.job_rollup_payload`;
null for a single run), and ordered by a rollup field with a ``job:*`` sort.

The top-level rows are few (tens to thousands), so a ``job:*`` order is the
board's default order of them stably sorted by the summaries, memoized per
base, time bucket and minute (the summaries' throughput and ETA follow
:func:`~vmn_exp.ui.job_rollup_cache.minute`). Rows without the value (single runs, a job without the metric)
come last, ties keep the default order.
"""
from operator import itemgetter

from vmn_exp.core.log import sort_descending
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.job_rollup_cache import minute
from vmn_exp.ui.leaderboard_live import Desc
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.experiments import _DESCENDING as DESCENDING

# sort key -> summary field
JOB_SORTS = {
    "job:progress": "progress",
    "job:failed_pct": "failed_pct",
    "job:throughput": "throughput_per_min",
    "job:best": "best",
    "job:total": "total",
    "job:started": "started_at",
}


def check_job_sort(sort, top):
    if sort in JOB_SORTS and not top:
        raise ValueError(f"sort {sort} needs top=1")


def sortable(value):
    return isinstance(value, str) or is_finite_number(value)


def job_descending(field, order, summaries, schema):
    """Most first unless *order* says otherwise; ``best`` best-first by its goal."""
    descending = DESCENDING.get(order)
    if descending is not None:
        return descending
    if field != "best":
        return True
    metric = next((s["metric"] for s in summaries.values() if s.get("metric")), None)
    return bool(metric) and sort_descending(schema, metric)


def job_value(summaries, row, field):
    """*row*'s job summary *field*, None when missing or not sortable."""
    value = (summaries.get(row["verstr"]) or {}).get(field)
    return value if sortable(value) else None


def job_key(value, descending, rest):
    """A ``job:*`` order's sort key: rows with the *value* first, by it,
    the rest after; *rest* (the default order's key) breaks ties."""
    if value is None:
        return (1, rest)
    return (0, Desc(value) if descending else value, rest)


def job_sorted(rows, summaries, sort, order, schema):
    """*rows* (in the default order) ordered by their job summary's *sort* field."""
    field = JOB_SORTS[sort]
    descending = job_descending(field, order, summaries, schema)
    keyed = [(job_key(job_value(summaries, row, field), descending, i), row)
             for i, row in enumerate(rows)]
    return [row for _, row in sorted(keyed, key=itemgetter(0))]


class JobsView:
    def __init__(self, cache, size=32):
        self._cache = cache
        self._orders = cache.generations.track(LRU(size))

    def ordered(self, snapshot, schema, last, f):
        """The rows passing the :class:`~vmn_exp.ui.leaderboard_scope.Filters`
        *f* in order, a ``job:*`` sort included."""
        cache = self._cache
        check_job_sort(f.sort, f.top)
        if f.sort not in JOB_SORTS:
            return cache._ordered(snapshot, schema, last, f)
        base, bucket = cache._base(snapshot)
        key = (base.token, bucket, minute(), cache.schema_key(schema), last) + f
        return self._orders.get(key, lambda: job_sorted(
            cache._ordered(snapshot, schema, last, f._replace(sort=None, order=None)),
            cache.job_rollups(snapshot, schema), f.sort, f.order, schema))

    def with_jobs(self, snapshot, schema, rows):
        """Copies of *rows* carrying ``job``."""
        summaries = self._cache.job_rollups(snapshot, schema)
        return [dict(row, job=summaries.get(row["verstr"])) for row in rows]
