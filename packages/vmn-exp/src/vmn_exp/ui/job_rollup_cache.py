#!/usr/bin/env python3
"""Job rollups memoized per index snapshot and time bucket, the way
:class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache` keeps its orders:
one :class:`~vmn_exp.ui.job_rollup.StaticRollups` per (base, schema), moved
on from the last one served for the app and schema across the deltas since
(else built), one live overlay per time bucket, and the JSON answers per
(base, bucket, clock bucket, schema) — a request is a memo hit.
"""
import vmn_exp.core.status as experiment_status
from vmn_exp.ui.job_rollup import JobTree, StaticRollups, overlay
from vmn_exp.ui.job_rollup_payload import job_payload, job_summary
from vmn_exp.ui.job_tally import RollupSpec
from vmn_exp.ui.memo import LRU

# Rollups moved on across generations: one per (app, schema) in use.
LATEST_ROLLUPS = 16
ANSWERS = 256


class JobRollupCache:
    def __init__(self, cache, size=32):
        self._cache = cache
        self._static = LRU(size)
        self._latest = LRU(LATEST_ROLLUPS)
        self._overlays = LRU(size)
        self._trees = LRU(size)
        self._answers = LRU(ANSWERS)

    def job_rollup(self, snapshot, schema, verstr):
        """*verstr*'s full rollup, or None when it is not a job."""
        return self._answer(snapshot, schema, verstr)

    def job_rollups(self, snapshot, schema):
        """``{verstr: compact summary}`` for every job."""
        return self._answer(snapshot, schema, None)

    def _answer(self, snapshot, schema, verstr):
        cache = self._cache
        base, bucket = cache._base(snapshot)
        tree = self._trees.get(base.token, lambda: JobTree(base))
        if verstr is not None and verstr not in tree.jobs:
            return None
        schema_key = cache.schema_key(schema)
        key = (base.token, bucket, cache._bucket(), schema_key, verstr)
        return self._answers.get(key, lambda: self._compute(
            snapshot, base, bucket, tree, schema, schema_key, verstr))

    def _compute(self, snapshot, base, bucket, tree, schema, schema_key, verstr):
        static = self._static.get(
            (base.token, schema_key),
            lambda: self._static_of(snapshot, base, schema, schema_key),
        )
        live = self._overlays.get((base.token, bucket, schema_key),
                                  lambda: overlay(base, bucket, static.spec))
        now = experiment_status._now()

        def parts(job):
            sources = (static.tallies, live)
            return [s[j] for j in tree.subtree_jobs(job) for s in sources if j in s]

        def row(job):
            return base.rows[base.position[job]]

        def summary(job):
            out = job_summary(row(job), parts(job), static.spec, now)
            best = out["best_verstr"]
            out["best_idx"] = row(best)["idx"] if best in base.position else None
            return out

        if verstr is not None:
            return job_payload(row(verstr), parts(verstr), static.spec, now)
        return {job: summary(job) for job in tree.jobs}

    def _static_of(self, snapshot, base, schema, schema_key):
        key = (snapshot.app_name, schema_key)
        last = self._latest.peek(key)
        moves = last and self._cache._deltas.since(last.token, base)
        static = last.advanced(base, *moves) if moves else StaticRollups.build(
            base, RollupSpec(schema))
        self._latest.put(key, static)
        return static
