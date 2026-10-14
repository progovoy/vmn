#!/usr/bin/env python3
"""What a job's page reads (plan 23 S3), off a
:class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache`: the summary (the
S1 rollup, the job's own row fields, its top 10 on the main metric), the
failure clusters, and the run detail's tree fields and fleet counts — none
of it reading a run state. Each answer is memoized per (index generation,
time bucket); the top 10 and the clusters cost one walk of the subtree when
built, the rest is the rollup's.
"""
import heapq

from vmn_exp.core.tree import subtree_verstrs
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.job_failures import failure_clusters
from vmn_exp.ui.leaderboard_facets import visible
from vmn_exp.ui.memo import LRU

TOP = 10
ANSWERS = 256
TREE_FIELDS = ("children", "kind", "depth", "tree_status", "child_counts",
               "sweep_planned", "sweep_trials")


def _top_entry(row, metric):
    return {"verstr": row["verstr"], "idx": row.get("idx"), "name": row.get("name"),
            "status": row.get("status"), "value": row["metrics"][metric]}


def top_rows(rows, metric, descending, count=TOP):
    """The best *count* of *rows* on *metric* (ties: the lowest verstr)."""
    if metric is None:
        return []
    sign = -1 if descending else 1
    scored = (r for r in rows if is_finite_number(r["metrics"].get(metric)))
    best = heapq.nsmallest(count, scored, key=lambda r: (sign * r["metrics"][metric], r["verstr"]))
    return [_top_entry(row, metric) for row in best]


def fleet_counts(rollup):
    """The run detail's ``fleet`` from a job's rollup (``created`` = never
    ran, ``waiting`` = not created yet)."""
    counts, expected = rollup["counts"], rollup["expected"]
    return {"expected": expected, "counts": {
        "running": counts["running"], "succeeded": counts["succeeded"],
        "failed": counts["failed"], "stuck": counts["stuck"], "created": counts["waiting"],
        "waiting": max(0, expected - rollup["total"]),
    }}


def _is_sweep(row, first_child):
    tags = (first_child or {}).get("tags") or {}
    return row.get("sweep_planned") is not None or "sweep_trial" in tags


class JobViews:
    def __init__(self, cache):
        self.cache = cache
        self._memo = LRU(ANSWERS)

    def _view(self, snapshot):
        """``(base, bucket, {position: row as of the bucket})``."""
        base, bucket = self.cache._base(snapshot)
        patched = self._memo.get(("patched", base.token, bucket), lambda: dict(
            zip(base.patch.changed, base.changed_at(bucket))))
        return base, bucket, patched

    def is_job(self, snapshot, verstr):
        base, _ = self.cache._base(snapshot)
        return verstr in self.cache._jobs.tree(base).jobs

    def etag(self, snapshot, schema, verstr, **params):
        """Changes whenever an answer for *verstr* could: generation, time
        bucket, and the minute (throughput and ETA count back from now)."""
        return self.cache.etag(snapshot, schema, job=verstr, minute=self._minute(), **params)

    def _minute(self):
        return self.cache._bucket() * self.cache.bucket_sec // 60

    def _memoized(self, snapshot, schema, verstr, kind, build, *extra):
        if not self.is_job(snapshot, verstr):
            return None
        base, bucket, _ = self._view(snapshot)
        key = (kind, base.token, bucket, self._minute(), self.cache.schema_key(schema),
               verstr) + extra
        return self._memo.get(key, build)

    def _row(self, snapshot, verstr):
        base, _, patched = self._view(snapshot)
        at = base.position[verstr]
        return patched.get(at, base.rows[at])

    def subtree_rows(self, snapshot, verstr):
        """The visible rows under *verstr* (not itself), as of now."""
        base, _, patched = self._view(snapshot)
        at = (base.position.get(v) for v in subtree_verstrs(verstr, base.children_of)
              if v != verstr)
        return visible([patched.get(i, base.rows[i]) for i in at if i is not None], False)

    def summary(self, snapshot, schema, verstr):
        """The job's rollup with its row fields and ``top``, or None."""
        return self._memoized(snapshot, schema, verstr, "summary",
                              lambda: self._summary(snapshot, schema, verstr))

    def _summary(self, snapshot, schema, verstr):
        row, spec = self._row(snapshot, verstr), self.cache._jobs.spec(snapshot, schema)
        main = spec.main if spec.ranked else None
        rows = self.subtree_rows(snapshot, verstr) if main else []
        first = self._first_child(snapshot, verstr)
        return {
            **self.cache.job_rollup(snapshot, schema, verstr),
            "name": row.get("name"), "idx": row.get("idx"), "status": row.get("status"),
            "tree_status": row.get("tree_status"), "kind": row.get("kind"),
            "sweep": _is_sweep(row, first),
            "top": top_rows(rows, main, main and spec.descending[main]),
        }

    def _first_child(self, snapshot, verstr):
        base, _ = self.cache._base(snapshot)
        kids = [k for k in base.children_of.get(verstr, ()) if k in base.position]
        return self._row(snapshot, kids[0]) if kids else None

    def failures(self, snapshot, schema, verstr, limit=20):
        """``{total_failed, clusters}`` of the job, or None."""
        return self._memoized(snapshot, schema, verstr, "failures", lambda: failure_clusters(
            self.cache._jobs.failure_counts(snapshot, schema, verstr),
            self.subtree_rows(snapshot, verstr), limit), limit)

    def detail_status(self, snapshot, schema, verstr):
        """The run detail's tree fields and ``fleet`` of a job, or None."""
        return self._memoized(snapshot, schema, verstr, "detail",
                              lambda: self._detail_status(snapshot, schema, verstr))

    def _detail_status(self, snapshot, schema, verstr):
        row = self._row(snapshot, verstr)
        fields = {k: row[k] for k in TREE_FIELDS if k in row}
        rollup = self.cache.job_rollup(snapshot, schema, verstr)
        return dict(fields, fleet=fleet_counts(rollup))

    def job_summary(self, snapshot, schema, verstr):
        """The job's compact rollup (a Jobs view row's ``job``), or None."""
        return self.cache.job_rollups(snapshot, schema).get(verstr)
