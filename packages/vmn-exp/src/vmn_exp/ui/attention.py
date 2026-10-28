#!/usr/bin/env python3
"""An app's attention queries counted (plan 28 P1): settings/conf
``experiment.ui.attention`` (:func:`~vmn_exp.core.app_settings.attention_entries`).

A query's count is the length of the board's own cached order for it
(:meth:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache.ordered`), so a
time-free query moves by the index deltas like any board filter, and
following its part lands on an order already built. ``ago()`` is pinned to
the minute (:func:`pinned`) before a board or a count sees a query: the
pinned text keys every cache, so an ``ago()`` order is built again at most
once a minute. Per outer run (the Jobs view's ``job.attention``) a query's
matching rows are counted by their top-level run, once per base, time
bucket and minute.
"""
from collections import Counter, namedtuple

import vmn_exp.core.status as experiment_status
from vmn_exp.core.query import QueryError, pin_ago
from vmn_exp.ui.job_rollup_cache import minute
from vmn_exp.ui.memo import LRU

# One configured query as the caches key it (labels are display only).
AttentionQuery = namedtuple("AttentionQuery", "key query level")
ERROR = "error"


def queries_of(entries):
    """The hashable :class:`AttentionQuery` tuple of *entries*."""
    return tuple(AttentionQuery(e["key"], e["query"], e["level"]) for e in entries)


def pinned(query):
    """*query* with its ``ago()`` pinned to the current minute."""
    now = experiment_status._now().replace(second=0, microsecond=0)
    return pin_ago(query, now=now)


def attention_key(entries):
    """*entries* as the caches key them: each query pinned (as given when it
    does not compile), so an ``ago()`` one moves with the minute."""
    return [(e["key"], e["label"], e["level"], _pinned_or_raw(e["query"])) for e in entries]


def _pinned_or_raw(query):
    try:
        return pinned(query)
    except QueryError:
        return query


def attention_payload(cache, snapshot, schema, entries, scope=None):
    """``[{key, label, level, count, q}]`` of *entries* over *snapshot*'s
    non-archived runs (*scope*'s subtree when given); a query that does not
    compile counts None with its ``error``."""
    parts = []
    for entry in entries:
        part = {"key": entry["key"], "label": entry["label"], "level": entry["level"],
                "count": None, "q": entry["query"]}
        try:
            part["count"] = len(cache.ordered(snapshot, schema, query=pinned(entry["query"]),
                                              scope=scope))
        except QueryError as e:
            part["error"] = str(e)
        parts.append(part)
    return parts


def severity(summary, counts, queries):
    """An outer run's attention rank: its error-level matches (stuck runs
    included), then its warn-level ones — ``errors + warns / (warns + 1)``."""
    stuck = (summary.get("counts") or {}).get("stuck", 0)
    errors = stuck + sum(counts.get(q.key, 0) for q in queries if q.level == ERROR)
    warns = sum(counts.get(q.key, 0) for q in queries if q.level != ERROR)
    return errors + warns / (warns + 1)


class AttentionCounts:
    """Per base, time bucket and minute: the Jobs view's summaries with
    their attention counts."""

    def __init__(self, cache, size=16):
        self._cache = cache
        self._summaries = cache.generations.track(LRU(size))
        self._by_root = cache.generations.track(LRU(size))

    def summaries(self, snapshot, schema, queries):
        """``{job: summary}``, each with ``attention`` (``{key: n}``, the runs
        of its tree each of *queries* matches, itself included; only given
        *queries*) and ``attention_rank`` (:func:`severity`)."""
        cache = self._cache
        base, bucket = cache._base(snapshot)
        key = (base.token, bucket, minute(), cache.schema_key(schema), queries)
        return self._summaries.get(key, lambda: self._merged(snapshot, schema, queries))

    def _merged(self, snapshot, schema, queries):
        """The job summaries (they follow the minute) with :meth:`by_root`'s
        counts, which move only with the board or an ``ago()`` query's pin."""
        by_root, out = self.by_root(snapshot, schema, queries), {}
        for job, summary in self._cache.job_rollups(snapshot, schema).items():
            counts = by_root.get(job, {})
            extra = {"attention_rank": severity(summary, counts, queries)}
            if queries:
                extra["attention"] = {q.key: counts.get(q.key, 0) for q in queries}
            out[job] = dict(summary, **extra)
        return out

    def by_root(self, snapshot, schema, queries):
        """``{top-level verstr: {key: n}}``: each query's matching runs per tree."""
        cache = self._cache
        base, bucket = cache._base(snapshot)
        texts = tuple(_pinned_or_raw(q.query) for q in queries)
        key = (base.token, bucket, cache.schema_key(schema), texts)
        return self._by_root.get(key, lambda: self._count(snapshot, schema, queries, texts))

    def _count(self, snapshot, schema, queries, texts):
        out = {}
        for q, text in zip(queries, texts):
            try:
                rows = self._cache.ordered(snapshot, schema, query=text)
            except QueryError:
                continue
            for root, n in Counter(row["root"] or row["verstr"] for row in rows).items():
                out.setdefault(root, {})[q.key] = n
        return out
