#!/usr/bin/env python3
"""What a group of the grouped Jobs view (``top=1|jobs|singles``, plan 23
S7) adds: its jobs' rollups summed. ``job_counts``: the group's jobs, per
tree status (the count names of plan 22); ``runs``: every job's ``total``
(its subtree) plus the group's single runs; ``failed``: failed, stuck or
lost runs among those; ``job_aggregates``: ``{metric: stats}`` over the group's jobs'
``best`` of the rollups' main metric (mean/best/median/min/max of the
bests, ``best`` by the metric's goal).

Built once per grouping and job summaries (which follow the live bucket and the minute):
O(jobs), not O(rows).
"""
from vmn_exp.core.metric_schema import metric_goal
from vmn_exp.core.settle import LOST
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.leaderboard_group_fields import COUNT_KEYS, COUNT_OF
from vmn_exp.ui.leaderboard_group_summary import stats

FAILED = ("failed", "stuck")


class JobGroups:
    def __init__(self, grouping, summaries):
        self._grouping, self._schema = grouping, grouping.spec.schema
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
            "job_aggregates": self._aggregates([s for _, s in jobs]),
        }

    def _aggregates(self, summaries):
        metric = next((s["metric"] for s in summaries if s.get("metric")), None)
        bests = sorted(s["best"] for s in summaries if is_finite_number(s.get("best")))
        if not bests:
            return {}
        return {metric: stats(bests, metric_goal(self._schema, metric))}


def job_fields(grouping, summaries):
    """``key -> fields`` for *grouping*'s groups, memoized on the grouping."""
    memo = grouping._job_groups
    if memo is None or memo[0] is not summaries:
        memo = grouping._job_groups = (summaries, JobGroups(grouping, summaries))
    return memo[1].fields
