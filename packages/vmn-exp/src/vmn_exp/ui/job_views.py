#!/usr/bin/env python3
"""What a job's page reads (plan 23 S3), off a
:class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache`: the summary (the
S1 rollup, the job's own row fields, its top 10 on the main metric), the
failure clusters, and the run detail's tree fields and fleet counts — none
of it reading a run state. Each answer shares the rollups' memo
(:meth:`~vmn_exp.ui.job_rollup_cache.JobRollupCache.answer`); the top 10 and
the clusters are each one pass over the subtree's rows, the rest is the
rollup's.
"""
import heapq
from operator import itemgetter

from vmn_exp.core.settle import LOST, NEVER_STARTED, split_slots
from vmn_exp.ui.job_failures import failure_clusters
from vmn_exp.ui.job_rollup_cache import minute
from vmn_exp.ui.leaderboard_facets import visible
from vmn_exp.ui.job_units import own_value
from vmn_exp.ui.leaderboard_scope import children_positions, is_flat, scope_positions

TOP = 10
TREE_FIELDS = ("children", "kind", "depth", "settled", "tree_status", "child_counts",
               "sweep_planned", "sweep_trials")


def _top_entry(row, metric):
    return {"verstr": row["verstr"], "idx": row.get("idx"), "name": row.get("name"),
            "status": row.get("status"), "value": row["metrics"][metric]}


def best_rows(values, descending, count=TOP):
    """The rows of the best *count* ``(verstr, value or None, row)``
    *values* (ties: the lowest verstr, then the first), best first."""
    sign = -1 if descending else 1
    scored = ((sign * value, verstr, i) for i, (verstr, value, _) in enumerate(values)
              if value is not None)
    return [values[i][2] for _, _, i in heapq.nsmallest(count, scored)]


def own_values(rows, metric):
    """``[(verstr, own value or None, row)]`` of *rows* (:func:`own_value`)."""
    return [(row["verstr"], own_value(row, metric), row) for row in rows]


def top_rows(rows, metric, descending, count=TOP):
    """The best *count* of *rows* on *metric* (ties: the lowest verstr)."""
    if metric is None:
        return []
    best = best_rows(own_values(rows, metric), descending, count)
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


def visible_rows(base, patched, verstrs):
    """The visible rows of the present *verstrs*, as of the bucket *patched* is of."""
    at = (base.position[v] for v in verstrs if v in base.position)
    return visible([patched.get(i, base.rows[i]) for i in at], False)


def child_rows(base, patched, verstr):
    """The visible rows right under *verstr*, as of the bucket *patched* is of."""
    return visible_rows(base, patched, base.children_of.get(verstr, ()))


def child_values(base, patched, verstr, metric):
    """:func:`own_values` of the visible rows right under *verstr* in
    storage order, as of the bucket *patched* is of: one pass over them."""
    rows, out = base.rows, []
    for i in children_positions(base, verstr):
        row = patched.get(i, rows[i])
        if not row.get("archived"):
            out.append((row["verstr"], own_value(row, metric), row))
    return out


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

    def row(self, snapshot, verstr):
        """*verstr*'s row as of now."""
        base, patched = self._view(snapshot)
        at = base.position[verstr]
        return patched.get(at, base.rows[at])

    def subtree_rows(self, snapshot, verstr):
        """The visible rows under *verstr* (not itself), as of now."""
        base, patched = self._view(snapshot)
        return visible([patched.get(i, base.rows[i]) for i in scope_positions(base, verstr)],
                       False)

    def rows_of(self, snapshot, verstrs):
        """The visible rows of the present *verstrs*, as of now."""
        return visible_rows(*self._view(snapshot), verstrs)

    def children(self, snapshot, verstr):
        """The visible rows right under *verstr*, as of now."""
        return child_rows(*self._view(snapshot), verstr)

    def summary(self, snapshot, schema, verstr, split=None):
        """The job's rollup with its row fields and ``top``, or None; with
        a *split* field (``tags.<k>``/``params.<k>``) its counts and
        durations per value as ``by`` (plan 28 P3)."""
        return self.rollups.answer(snapshot, schema, verstr, ("summary", split),
                                   lambda: self._summary(snapshot, schema, verstr, split))

    def _summary(self, snapshot, schema, verstr, split):
        row = self.row(snapshot, verstr)
        first = self._first_child(snapshot, verstr)
        return {
            **self.rollups.job_rollup(snapshot, schema, verstr),
            "name": row.get("name"), "idx": row.get("idx"), "status": row.get("status"),
            "tree_status": row.get("tree_status"), "kind": row.get("kind"),
            "sweep": _is_sweep(row, first),
            "top": self._top(snapshot, schema, verstr),
            "split": split,
            "by": split and self.rollups.split_rollup(snapshot, split, verstr),
            "rolled": self.cache.job_aggregates.one(snapshot, schema, verstr),
        }

    def _top(self, snapshot, schema, verstr):
        """The job's best :data:`TOP` on the main metric: one pass over its
        subtree's rows as of now, no order built; a job of leaves reads the
        children values its ``rolled`` reads too."""
        spec = self.rollups.spec(snapshot, schema)
        main = spec.main if spec.ranked else None
        if main is None:
            return []
        base, _ = self.cache._base(snapshot)
        if is_flat(base.children_of, verstr):
            values = self.cache.job_aggregates.child_values(snapshot, verstr, main)
        else:
            values = own_values(self.subtree_rows(snapshot, verstr), main)
        up = spec.up[main]
        return top_rows(best_rows(values, up), main, up)

    def _first_child(self, snapshot, verstr):
        base, _ = self.cache._base(snapshot)
        first = next((k for k in base.children_of.get(verstr, ()) if k in base.position), None)
        return None if first is None else self.row(snapshot, first)

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
        row = self.row(snapshot, verstr)
        fields = {k: row[k] for k in TREE_FIELDS if k in row}
        rollup = self.rollups.job_rollup(snapshot, schema, verstr)
        return dict(fields, fleet=fleet_counts(rollup))

    def job_summary(self, snapshot, schema, verstr):
        """The job's compact rollup (a Jobs view row's ``job``), or None."""
        return self.rollups.job_rollups(snapshot, schema).get(verstr)
