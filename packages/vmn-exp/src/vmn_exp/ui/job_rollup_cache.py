#!/usr/bin/env python3
"""Job rollups memoized per index snapshot and time bucket, the way
:class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache` keeps its orders:
one :class:`~vmn_exp.ui.job_rollup.StaticRollups` per (base, schema), moved
on from the last one served for the app and schema across the deltas since
(else built), one live overlay per time bucket, and every job answer (these
rollups and :class:`~vmn_exp.ui.job_views.JobViews`') in one memo per
(base, live bucket, :func:`minute`, schema) — a request is a memo hit.
"""
import vmn_exp.core.status as experiment_status
from vmn_exp.ui.job_rollup import JobTree, StaticRollups, overlay
from vmn_exp.ui.job_rollup_payload import failure_counts, job_payload, job_summary
from vmn_exp.ui.job_tally import RollupSpec
from vmn_exp.ui.memo import LRU

# Rollups moved on across generations: one per (app, schema) in use.
LATEST_ROLLUPS = 16
ANSWERS = 256


def minute():
    """The clock job answers follow besides the live bucket: throughput and
    ETA count completions per minute back from now."""
    return int(experiment_status._now().timestamp() // 60)


def _payload(job, parts, spec, now, idx_of):
    return job_payload(job, parts, spec, now)


def _failure_counts(job, parts, spec, now, idx_of):
    return failure_counts(parts)


class JobRollupCache:
    def __init__(self, cache, size=32):
        self._cache = cache
        track = cache.generations.track
        self._static = track(LRU(size))
        self._latest = LRU(LATEST_ROLLUPS)
        self._overlays = track(LRU(size))
        self._trees = track(LRU(size))
        self._answers = track(LRU(ANSWERS))
        self._specs = track(LRU(size))

    def job_rollup(self, snapshot, schema, verstr):
        """*verstr*'s full rollup, or None when it is not a job."""
        return self._rolled_up(snapshot, schema, verstr, _payload)

    def job_rollups(self, snapshot, schema):
        """``{verstr: compact summary}`` for every job."""
        return self._rolled_up(snapshot, schema, None, job_summary)

    def failure_counts(self, snapshot, schema, verstr):
        """``{failure signature: runs}`` over *verstr*'s subtree, or None
        when it is not a job."""
        return self._rolled_up(snapshot, schema, verstr, _failure_counts)

    def spec(self, snapshot, schema):
        """The :class:`~vmn_exp.ui.job_tally.RollupSpec` of *schema* over
        *snapshot* (its fallback metrics are the snapshot's most common)."""
        cache = self._cache
        base, _ = cache._base(snapshot)
        return self._specs.get((base.token, cache.schema_key(schema)), lambda: RollupSpec(
            schema, lambda: cache._facets.common_metrics(snapshot)))

    def tree(self, base):
        """*base*'s :class:`~vmn_exp.ui.job_rollup.JobTree`."""
        return self._trees.get(base.token, lambda: JobTree(base))

    def answer(self, snapshot, schema, verstr, kind, build):
        """*build()*, memoized per (base, live bucket, minute, schema, job,
        *kind*); None when *verstr* is not a job (None: every job)."""
        cache = self._cache
        base, bucket = cache._base(snapshot)
        if verstr is not None and verstr not in self.tree(base).jobs:
            return None
        key = (base.token, bucket, minute(), cache.schema_key(schema), verstr, kind)
        return self._answers.get(key, build)

    def _rolled_up(self, snapshot, schema, verstr, answer):
        return self.answer(snapshot, schema, verstr, answer,
                           lambda: self._compute(snapshot, schema, verstr, answer))

    def _compute(self, snapshot, schema, verstr, answer):
        base, bucket = self._cache._base(snapshot)
        tree, schema_key = self.tree(base), self._cache.schema_key(schema)
        spec = self.spec(snapshot, schema)
        static = self._static.get(
            (base.token, schema_key),
            lambda: self._static_of(snapshot, base, spec, schema_key),
        )
        live = self._overlays.get((base.token, bucket, schema_key),
                                  lambda: overlay(base, bucket, static.spec))
        now = experiment_status._now()

        def parts(job):
            sources = (static.tallies, live)
            return [s[j] for j in tree.subtree_jobs(job) for s in sources if j in s]

        def row(job):
            return base.rows[base.position[job]]

        def idx_of(job):
            return row(job)["idx"] if job in base.position else None

        def answered(job):
            return answer(row(job), parts(job), static.spec, now, idx_of)

        if verstr is not None:
            return answered(verstr)
        return {job: answered(job) for job in tree.jobs}

    def _static_of(self, snapshot, base, spec, schema_key):
        key = (snapshot.app_name, schema_key)
        last = self._latest.peek(key)
        moves = last and last.spec.same_metrics(spec) and self._cache._deltas.since(
            last.token, base)
        static = last.advanced(base, *moves) if moves else StaticRollups.build(base, spec)
        self._latest.put(key, static)
        return static
