#!/usr/bin/env python3
"""What a group of the grouped Jobs view (``top=1|jobs|singles``, plan 23
S7) adds: its jobs' rollups summed. ``job_counts``: the group's jobs, per
tree status (the count names of plan 22); ``runs``: every job's ``total``
(its subtree) plus the group's single runs; ``failed``: failed, stuck or
lost runs among those; ``run_counts``: the jobs' ``counts`` summed;
``lost``: their lost runs (plan 34 §3, outside ``run_counts``);
``job_aggregates``: ``{metric: header}``, the units of all the group's jobs
pooled under the board's chosen aggregate (plan 34 §1: the jobs are the
attempts of one training; a unit key in several counts from the latest,
by its job's start, else its creation; see
:meth:`~vmn_exp.ui.job_aggregate.Pool.pooled`).

Built once per grouping, job summaries (which follow the live bucket and the
minute) and aggregate pool: O(the group's jobs and their memoized units),
not O(rows).
"""
import datetime
from collections import Counter

from vmn_exp.core.settle import LOST
from vmn_exp.core.status import parse_iso
from vmn_exp.ui.leaderboard_group_fields import COUNT_KEYS, COUNT_OF

FAILED = ("failed", "stuck")
_EPOCH = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


class JobGroups:
    def __init__(self, grouping, summaries, pool):
        self._grouping, self._pool = grouping, pool
        spec = grouping.spec
        rows = [row for row in map(grouping.row_of, summaries) if row is not None]
        self._jobs = {}  # {group key: [(job row, summary)]}
        snapshot = grouping.base.snapshot
        key_of = spec.key_of(snapshot)
        for row in spec.filtered(snapshot, rows):
            self._jobs.setdefault(key_of(row), []).append((row, summaries[row["verstr"]]))
        self._fields = {}

    def fields(self, key):
        found = self._fields.get(key)
        if found is None:
            found = self._fields[key] = self._of(key)
        return found

    def _of(self, key):
        jobs = self._jobs.get(key, [])
        counts = dict.fromkeys(COUNT_KEYS, 0)
        for row, _ in jobs:
            name = COUNT_OF.get(row.get("tree_status"))
            if name:
                counts[name] += 1
        counts["total"] = len(jobs)
        own = self._grouping._own(key).counts()
        singles_failed = sum(own[s] for s in FAILED) - sum(
            1 for row, _ in jobs if row.get("status") in FAILED)
        return {
            "job_counts": counts,
            "runs": sum(s["total"] for _, s in jobs) + self._grouping.size(key) - len(jobs),
            "failed": singles_failed + sum(
                sum(s["counts"][f] for f in FAILED) + s[LOST] for _, s in jobs),
            "run_counts": _summed(s["counts"] for _, s in jobs),
            LOST: sum(s[LOST] for _, s in jobs),
            "job_aggregates": self._aggregates([row for row, _ in jobs]),
        }

    def _aggregates(self, rows):
        latest_first = [row["verstr"] for row in sorted(rows, key=attempt_order, reverse=True)]
        pooled = self._pool.pooled(latest_first)
        return {pooled["metric"]: pooled} if pooled else {}


def attempt_order(row):
    """An attempt's place among its group's: its start, else its creation
    (then its creation and verstr, for a tie)."""
    created = parse_iso(row.get("timestamp")) or _EPOCH
    return parse_iso(row.get("started_at")) or created, created, row["verstr"]


def _summed(counts):
    total = Counter()
    for c in counts:
        total.update(c)
    return dict(total)


def job_fields(grouping, summaries, pool):
    """``key -> fields`` for *grouping*'s groups, memoized on the grouping."""
    memo = grouping._job_groups
    if memo is None or memo[0] is not summaries or memo[1] is not pool:
        memo = grouping._job_groups = (summaries, pool, JobGroups(grouping, summaries, pool))
    return memo[2].fields
