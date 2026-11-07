#!/usr/bin/env python3
"""The Jobs view (plan 23 S2): the top-level rows (``top``), each carrying
``job``, its job's compact rollup (:mod:`~vmn_exp.ui.job_rollup_payload`;
null for a single run), and ordered by a rollup field with a ``job:*`` sort.

The top-level rows are few (tens to thousands), so a ``job:*`` order is the
board's default order of them stably sorted by the summaries, memoized per
base, time bucket and minute (the summaries' throughput and ETA follow
:func:`~vmn_exp.ui.job_rollup_cache.minute`). Rows without the value (single runs, a job without the metric)
come last, ties keep the default order. ``job:value`` sorts by each
top-level job's ``rolled`` (plan 31 §2, :mod:`~vmn_exp.ui.job_aggregate`;
the :class:`~vmn_exp.ui.leaderboard_scope.Filters`' ``job_agg``, else the
app's), best-first by its metric's goal. ``job:attention`` ranks by the
summaries' ``attention_rank`` (:mod:`~vmn_exp.ui.attention`), the app's
attention queries given. A tree page (``children_of``, plan 28 N6) sorts
its children by theirs (:mod:`~vmn_exp.ui.leaderboard_children`).
"""
from operator import itemgetter

from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.job_aggregate import board_job_agg
from vmn_exp.ui.job_rollup_cache import minute
from vmn_exp.ui.leaderboard_live import Desc
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers.experiments import _DESCENDING as DESCENDING

# sort key -> summary field (a dotted one is nested), the one its cell shows
JOB_SORTS = {
    "job:progress": "progress",
    "job:failed_pct": "failed_pct",
    "job:throughput": "throughput_per_min",
    "job:rate": "declared_progress.rate_per_min",
    "job:value": "rolled.value",
    "job:total": "total",
    "job:started": "when_at",
    "job:attention": "attention_rank",
}
ATTENTION_SORT = "job:attention"
VALUE_SORT = "job:value"


def check_job_sort(sort, top):
    if sort in JOB_SORTS and not top:
        raise ValueError(f"sort {sort} needs top=1 or children_of")


def sortable(value):
    return isinstance(value, str) or is_finite_number(value)


def job_descending(field, order, summaries, schema):
    """Most first unless *order* says otherwise; ``rolled.value`` best-first
    by its goal (ascending without one, plan 32)."""
    descending = DESCENDING.get(order)
    if descending is not None:
        return descending
    if field != JOB_SORTS[VALUE_SORT]:
        return True
    rolled = next((s["rolled"] for s in summaries.values() if s.get("rolled")), None)
    return bool(rolled) and rolled["goal"] == "max"


def job_value(summaries, row, field):
    """*row*'s job summary *field*, None when missing or not sortable."""
    value = summaries.get(row["verstr"])
    for part in field.split("."):
        value = (value or {}).get(part)
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


def _with_rolled(summaries, rolled):
    """*summaries* with ``rolled`` on the top-level jobs'."""
    return {job: dict(summary, rolled=rolled[job]) if job in rolled else summary
            for job, summary in summaries.items()}


class JobsView:
    def __init__(self, cache, size=32):
        self._cache = cache
        self._orders = cache.generations.track(LRU(size))
        self._rolled = cache.generations.track(LRU(size))

    def ordered(self, snapshot, schema, last, f, attention=()):
        """The rows passing the :class:`~vmn_exp.ui.leaderboard_scope.Filters`
        *f* in order, a ``job:*`` sort included (by the *attention* queries'
        counts for ``job:attention``)."""
        cache = self._cache
        check_job_sort(f.sort, f.top or f.children_of is not None)
        if f.sort not in JOB_SORTS:
            return cache._ordered(snapshot, schema, last, f)
        base, bucket = cache._base(snapshot)
        key = (base.token, bucket, minute(), cache.schema_key(schema), last, attention) + f
        return self._orders.get(key, lambda: job_sorted(
            cache._ordered(snapshot, schema, last, f._replace(sort=None, order=None)),
            self.summaries(snapshot, schema, f.sort, attention, f.children_of, f.job_agg),
            f.sort, f.order, schema))

    def summaries(self, snapshot, schema, sort=None, attention=(), children_of=None,
                  job_agg=None):
        """``{job: summary}``, with attention counts given *attention*
        queries or a ``job:attention`` *sort*; with *children_of*, its
        children's, each counted over its own subtree; else each top-level
        job's carrying ``rolled`` by *job_agg* (None: the app's)."""
        cache = self._cache
        if children_of is not None:
            return cache.tree_nodes.summaries(snapshot, schema, children_of, attention)
        counted = bool(attention or sort == ATTENTION_SORT)
        job_agg = job_agg or board_job_agg(cache, snapshot)
        base, bucket = cache._base(snapshot)
        key = (base.token, bucket, minute(), cache.schema_key(schema), attention, counted, job_agg)
        return self._rolled.get(key, lambda: _with_rolled(
            cache.attention.summaries(snapshot, schema, attention) if counted
            else cache.job_rollups(snapshot, schema),
            cache.job_aggregates.rolled(snapshot, schema, job_agg)))

    def with_jobs(self, snapshot, schema, rows, attention=(), job_agg=None):
        """Copies of *rows* carrying ``job`` (with its *attention* counts and ``rolled``)."""
        summaries = self.summaries(snapshot, schema, None, attention, job_agg=job_agg)
        return [dict(row, job=summaries.get(row["verstr"])) for row in rows]
