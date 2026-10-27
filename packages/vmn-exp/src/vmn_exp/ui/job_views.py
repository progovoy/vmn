#!/usr/bin/env python3
"""What a job's page reads (plan 23 S3), off a
:class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache`: the summary (the
S1 rollup, the job's own row fields, its top 10 on the main metric), the
failure clusters, and the run detail's tree fields and fleet counts — none
of it reading a run state. Each answer shares the rollups' memo
(:meth:`~vmn_exp.ui.job_rollup_cache.JobRollupCache.answer`); the top 10 is
a slice of the job's scoped order, the clusters one pass over the subtree's
rows, the rest is the rollup's.
"""
import heapq
from operator import itemgetter

from vmn_exp.core.log import primary_metric
from vmn_exp.core.settle import LOST, NEVER_STARTED, split_slots
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.job_failures import failure_clusters
from vmn_exp.ui.job_rollup_cache import minute
from vmn_exp.ui.leaderboard_facets import visible
from vmn_exp.ui.leaderboard_scope import Filters, scope_positions

TOP = 10
TREE_FIELDS = ("children", "kind", "depth", "settled", "tree_status", "child_counts",
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
    ran, ``waiting`` = not created yet), as
    :func:`~vmn_exp.core.tree.fleet_summary` counts it: an ended job's
    never-started runs and slots are ``never_started``, its stuck runs
    ``lost``, beside the counts."""
    counts, expected = rollup["counts"], rollup["expected"]
    waiting, slots_never = split_slots(max(0, expected - rollup["total"]), rollup["ended"])
    return {"expected": expected, "counts": {
        "running": counts["running"], "succeeded": counts["succeeded"],
        "failed": counts["failed"], "stuck": counts["stuck"], "created": counts["waiting"],
        "waiting": waiting,
    }, NEVER_STARTED: rollup[NEVER_STARTED] + slots_never, LOST: rollup[LOST]}


def _is_sweep(row, first_child):
    tags = (first_child or {}).get("tags") or {}
    return row.get("sweep_planned") is not None or "sweep_trial" in tags


def _leading(order, metric, count=TOP):
    """The first rows of *order* (ranked on *metric*, rows without a finite
    value last) holding its best *count* scored ones and any tied with the
    last of them, read a slice at a time."""
    out, scored, chunk = [], [], 2 * count
    value = lambda row: row["metrics"][metric]  # noqa: E731
    while len(out) < len(order):
        rows = order[len(out):len(out) + chunk]
        out += rows
        scored += [r for r in rows if is_finite_number(r["metrics"].get(metric))]
        if len(scored) < len(out):  # the unscored tail began
            break
        if len(scored) > count and value(scored[-1]) != value(scored[count - 1]):
            break
        chunk *= 2
    return scored


class JobViews:
    def __init__(self, cache):
        self.cache = cache
        self.rollups = cache.jobs

    def _view(self, snapshot):
        """``(base, {position: row as of now})``."""
        base, bucket = self.cache._base(snapshot)
        return base, base.patched(bucket)

    def is_job(self, snapshot, verstr):
        base, _ = self.cache._base(snapshot)
        return verstr in self.rollups.tree(base).jobs

    def etag(self, snapshot, schema, verstr, **params):
        """Changes whenever an answer for *verstr* could: generation, time
        bucket, and the minute (throughput and ETA count back from now)."""
        return self.cache.etag(snapshot, schema, job=verstr, minute=minute(), **params)

    def _row(self, snapshot, verstr):
        base, patched = self._view(snapshot)
        at = base.position[verstr]
        return patched.get(at, base.rows[at])

    def subtree_rows(self, snapshot, verstr):
        """The visible rows under *verstr* (not itself), as of now."""
        base, patched = self._view(snapshot)
        return visible([patched.get(i, base.rows[i]) for i in scope_positions(base, verstr)],
                       False)

    def summary(self, snapshot, schema, verstr):
        """The job's rollup with its row fields and ``top``, or None."""
        return self.rollups.answer(snapshot, schema, verstr, "summary",
                                   lambda: self._summary(snapshot, schema, verstr))

    def _summary(self, snapshot, schema, verstr):
        row = self._row(snapshot, verstr)
        first = self._first_child(snapshot, verstr)
        return {
            **self.rollups.job_rollup(snapshot, schema, verstr),
            "name": row.get("name"), "idx": row.get("idx"), "status": row.get("status"),
            "tree_status": row.get("tree_status"), "kind": row.get("kind"),
            "sweep": _is_sweep(row, first),
            "top": self._top(snapshot, schema, verstr),
        }

    def _top(self, snapshot, schema, verstr):
        """The job's best :data:`TOP` on the main metric: the head of its
        scoped static order (moved across generations, not rebuilt) and
        its rows a time bucket changes."""
        spec = self.rollups.spec(snapshot, schema)
        main = spec.main if spec.ranked else None
        if main is None:
            return []
        base, patched = self._view(snapshot)
        sort = None if main == primary_metric(schema) else main
        static = self.cache.static_order(base, schema, Filters(sort=sort, scope=verstr))
        live = [patched[i] for i in scope_positions(base, verstr) if i in patched]
        rows = _leading(static.sorted, main) + visible(live, False)
        return top_rows(rows, main, spec.descending[main])

    def _first_child(self, snapshot, verstr):
        base, _ = self.cache._base(snapshot)
        kids = [k for k in base.children_of.get(verstr, ()) if k in base.position]
        return self._row(snapshot, kids[0]) if kids else None

    def failures(self, snapshot, schema, verstr, limit=20):
        """``{total_failed, clusters}`` of the job, or None."""
        return self.rollups.answer(snapshot, schema, verstr, ("failures", limit), lambda: (
            failure_clusters(self.rollups.failure_counts(snapshot, schema, verstr),
                             self.subtree_rows(snapshot, verstr), limit,
                             sig=itemgetter("failure_sig"))))

    def detail_status(self, snapshot, schema, verstr):
        """The run detail's tree fields and ``fleet`` of a job, or None."""
        return self.rollups.answer(snapshot, schema, verstr, "detail",
                                   lambda: self._detail_status(snapshot, schema, verstr))

    def _detail_status(self, snapshot, schema, verstr):
        row = self._row(snapshot, verstr)
        fields = {k: row[k] for k in TREE_FIELDS if k in row}
        rollup = self.rollups.job_rollup(snapshot, schema, verstr)
        return dict(fields, fleet=fleet_counts(rollup))

    def job_summary(self, snapshot, schema, verstr):
        """The job's compact rollup (a Jobs view row's ``job``), or None."""
        return self.rollups.job_rollups(snapshot, schema).get(verstr)
