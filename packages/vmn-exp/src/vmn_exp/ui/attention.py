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

Built-in parts (:mod:`~vmn_exp.ui.attention_built_in`) come first, counted
from the live rows instead, and are shown only while they count any.
"""
from collections import Counter, namedtuple

import vmn_exp.core.status as experiment_status
from vmn_exp.core.query import QueryError, pin_ago
from vmn_exp.ui.attention_built_in import built_in_count, built_in_rows, is_built_in, shown
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
            part["count"] = _count(cache, snapshot, schema, entry, scope)
        except QueryError as e:
            part["error"] = str(e)
        if shown(part["key"], part["count"]):
            parts.append(part)
    return parts


def _count(cache, snapshot, schema, entry, scope):
    if is_built_in(entry["key"]):
        return built_in_count(cache, snapshot, entry["key"], scope)
    return len(cache.ordered(snapshot, schema, query=pinned(entry["query"]), scope=scope))


def severity(summary, counts, queries):
    """An outer run's attention rank: its error-level matches (stuck runs
    included), then its warn-level ones — ``errors + warns / (warns + 1)``."""
    stuck = (summary.get("counts") or {}).get("stuck", 0)
    errors = stuck + sum(counts.get(q.key, 0) for q in queries if q.level == ERROR)
    warns = sum(counts.get(q.key, 0) for q in queries if q.level != ERROR)
    return errors + warns / (warns + 1)


def with_attention(summary, counts, queries):
    """A copy of the job *summary* with ``attention_rank`` and, when any part
    is shown, ``attention`` (*counts*: ``{key: n}`` of its tree)."""
    extra = {"attention_rank": severity(summary, counts, queries)}
    parts = {q.key: counts.get(q.key, 0) for q in queries if shown(q.key, counts.get(q.key, 0))}
    if parts:
        extra["attention"] = parts
    return dict(summary, **extra)


def pinned_texts(queries):
    """Each of *queries*' text pinned (as given when it does not compile)."""
    return tuple(_pinned_or_raw(q.query) for q in queries)


class AttentionCounts:
    """Per base, time bucket and minute: the Jobs view's summaries with
    their attention counts."""

    def __init__(self, cache, size=16):
        self._cache = cache
        self._summaries = cache.generations.track(LRU(size))
        self._by_root = cache.generations.track(LRU(size))
        self._matches = cache.generations.track(LRU(size))

    def summaries(self, snapshot, schema, queries):
        """``{job: summary}``, each with ``attention`` (``{key: n}``, the runs
        of its tree each of *queries* matches, itself included; only given
        *queries*, a built-in one only while it counts any) and
        ``attention_rank`` (:func:`severity`)."""
        cache = self._cache
        base, bucket = cache._base(snapshot)
        key = (base.token, bucket, minute(), cache.schema_key(schema),
               cache.jobs.progress_names(snapshot), queries)
        return self._summaries.get(key, lambda: self._merged(snapshot, schema, queries))

    def _merged(self, snapshot, schema, queries):
        """The job summaries (they follow the minute) with :meth:`by_root`'s
        counts, which move only with the board or an ``ago()`` query's pin."""
        by_root = self.by_root(snapshot, schema, queries)
        return {job: with_attention(summary, by_root.get(job, {}), queries)
                for job, summary in self._cache.job_rollups(snapshot, schema).items()}

    def by_root(self, snapshot, schema, queries):
        """``{top-level verstr: {key: n}}``: each query's matching runs per tree."""
        cache = self._cache
        base, bucket = cache._base(snapshot)
        texts = pinned_texts(queries)
        key = (base.token, bucket, cache.schema_key(schema), texts)
        return self._by_root.get(key, lambda: {
            root: dict(Counter(k for k, _ in pairs))
            for root, pairs in self.matches(snapshot, schema, queries).items()})

    def matches(self, snapshot, schema, queries):
        """``{top-level verstr: [(key, matching verstr)]}``, once per base,
        time bucket and pinned query texts (the tree counts nodes from it too)."""
        cache = self._cache
        base, bucket = cache._base(snapshot)
        texts = pinned_texts(queries)
        key = (base.token, bucket, cache.schema_key(schema), texts)
        return self._matches.get(key, lambda: self._grouped(snapshot, schema, queries, texts))

    def _grouped(self, snapshot, schema, queries, texts):
        out = {}
        for q, text in zip(queries, texts):
            for row in self._matching(snapshot, schema, q, text):
                out.setdefault(row["root"] or row["verstr"], []).append((q.key, row["verstr"]))
        return out

    def _matching(self, snapshot, schema, q, text):
        """The runs *q* matches: a built-in part's, else its query's (none
        when it does not compile)."""
        if is_built_in(q.key):
            return built_in_rows(self._cache, snapshot, q.key)
        try:
            return self._cache.ordered(snapshot, schema, query=text)
        except QueryError:
            return ()
