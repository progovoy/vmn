#!/usr/bin/env python3
"""The tree's pages (plan 28 N6): ``children_of=<v>``, a run's direct
children in the board's order, filtered, sorted and paged like it (the
children orders are the board's own, in LRUs of their own:
:class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache`).

A child with children carries ``job``, its Jobs view summary
(:mod:`~vmn_exp.ui.job_rollup_payload`) with ``attention`` and
``attention_rank`` (:func:`~vmn_exp.ui.attention.with_attention`) over its
own subtree, itself included, and given a split field ``split`` and ``by``
(P3's counts per value). A child without children carries ``attention``
when it matches a query itself. Every child carries ``open``: whether the
tree unfolds it (attention or a live run below).

A query's matching runs, grouped by top-level run, are
:meth:`~vmn_exp.ui.attention.AttentionCounts.matches` (what the Jobs view
counts per tree too); here they are counted up the ancestor chains (to the
nearest archived job, :meth:`~vmn_exp.ui.job_rollup.JobTree.counted_in`) of
one tree at a time, the tree a request reads: O(that tree's matches × depth)
once per generation.
"""
from collections import Counter

from vmn_exp.ui.attention import pinned_texts, with_attention
from vmn_exp.ui.job_rollup_cache import minute
from vmn_exp.ui.memo import LRU


def tree_root(base, verstr):
    """The top-level run of *verstr*'s tree (itself for one the snapshot lacks)."""
    at = base.position.get(verstr)
    return (base.rows[at]["root"] if at is not None else None) or verstr


def opens(job):
    """Whether the tree unfolds a node of *job* summary: attention or live runs below."""
    if not job:
        return False
    counts = job.get("counts") or {}
    return bool(any((job.get("attention") or {}).values())
                or counts.get("running") or counts.get("stuck"))


class TreeNodes:
    def __init__(self, cache, size=32):
        self._cache = cache
        track = cache.generations.track
        self._counts = track(LRU(size))
        self._summaries = track(LRU(size))

    def rows(self, snapshot, schema, rows, parent, queries=(), split=None):
        """Copies of *parent*'s children *rows* as a tree page serves them."""
        summaries = self.summaries(snapshot, schema, parent, queries, split)
        counts = self.counts(snapshot, schema, parent, queries)
        out = []
        for row in rows:
            job = summaries.get(row["verstr"])
            node = dict(row, job=job, open=opens(job))
            own = counts.get(row["verstr"])
            if job is None and own:
                node["attention"] = dict(own)
            out.append(node)
        return out

    def summaries(self, snapshot, schema, parent, queries=(), split=None):
        """``{child: summary}`` of *parent*'s children with children, each
        with its subtree's attention counts for *queries* (and its runs per
        value of *split*)."""
        cache = self._cache
        base, bucket = cache._base(snapshot)
        key = (base.token, bucket, minute(), cache.schema_key(schema),
               cache.jobs.progress_names(snapshot), parent, queries, split)
        return self._summaries.get(key, lambda: self._summarized(snapshot, schema, parent,
                                                                 queries, split))

    def _summarized(self, snapshot, schema, parent, queries, split):
        cache = self._cache
        base = cache._base(snapshot)[0]
        rollups = cache.job_rollups(snapshot, schema)
        counts = self.counts(snapshot, schema, parent, queries)
        out = {}
        for child in base.children_of.get(parent, ()):
            if child in rollups:
                job = out[child] = with_attention(rollups[child], counts.get(child, {}), queries)
                if split:
                    job.update(split=split, by=cache.jobs.split_rollup(snapshot, split, child))
        return out

    def counts(self, snapshot, schema, parent, queries=()):
        """``{node: Counter({key: n})}`` over *parent*'s tree: the runs each
        query matches at or below each node."""
        if not queries:
            return {}
        base, bucket = self._cache._base(snapshot)
        texts, root = pinned_texts(queries), tree_root(base, parent)
        return self._counts.get(
            (base.token, bucket, texts, root),
            lambda: _counted(self._cache.attention.matches(snapshot, schema, queries).get(root, ()),
                             self._cache.jobs.tree(base)))


def _counted(matches, tree):
    counts = {}
    for key, verstr in matches:
        for node in tree.counted_in(verstr):
            counts.setdefault(node, Counter())[key] += 1
    return counts
