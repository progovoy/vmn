"""Archived runs leave every count above them: a job's rollup (total,
status counts, progress), its status summary and its attention counts —
an archived job takes its whole subtree out of the jobs above it, and
archiving a run moves the counts already served."""
import pytest
from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.ui.attention import AttentionQuery
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod

WAITING = (AttentionQuery("waiting", 'status = "created" and timestamp < ago("1h")', "warn"),)


@pytest.fixture
def tree(monkeypatch):
    """Driver D (running) -> outer O (running) -> 4 waiting runs; D -> 2 waiting runs."""
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(7)
    driver = fleet.append(state=running(T0))
    outer = fleet.append(parent=driver, state=running(T0))
    under_outer = [fleet.append(parent=outer) for _ in range(4)]
    beside = [fleet.append(parent=driver) for _ in range(2)]
    return fleet, driver, outer, under_outer, beside, LeaderboardCache()


def _archive(fleet, *verstrs):
    for verstr in verstrs:
        fleet.edit(fleet.index(verstr), archived=True)
    return fleet.snapshot()


def test_archiving_a_waiting_run_lowers_the_counts_already_served(tree):
    fleet, driver, outer, under_outer, _, cache = tree
    snap = fleet.snapshot()
    assert cache.job_rollups(snap, {})[driver]["counts"]["waiting"] == 6
    snap = _archive(fleet, *under_outer[:3])
    assert cache.job_rollups(snap, {})[driver]["counts"]["waiting"] == 3
    assert cache.job_rollup(snap, {}, outer)["total"] == 1
    assert cache.jobs.status_summary(snap, {}, driver)["counts"]["created"] == 3


def test_an_archived_job_takes_its_subtree_out_of_the_jobs_above(tree):
    fleet, driver, outer, _, _, cache = tree
    cache.job_rollups(fleet.snapshot(), {})
    snap = _archive(fleet, outer)
    rollup = cache.job_rollup(snap, {}, driver)
    assert rollup["total"] == 2
    assert rollup["counts"]["waiting"] == 2
    assert rollup["counts"]["running"] == 0
    assert cache.job_rollups(snap, {})[driver]["total"] == 2


def test_attention_counts_leave_archived_runs_out(tree):
    fleet, driver, outer, under_outer, _, cache = tree
    snap = fleet.snapshot()
    assert cache.attention.summaries(snap, {}, WAITING)[driver]["attention"]["waiting"] == 6
    snap = _archive(fleet, under_outer[0])
    assert cache.attention.summaries(snap, {}, WAITING)[driver]["attention"]["waiting"] == 5
    snap = _archive(fleet, outer)
    assert cache.attention.summaries(snap, {}, WAITING)[driver]["attention"]["waiting"] == 2
    nodes = cache.tree_nodes.counts(snap, {}, driver, WAITING)
    assert nodes[driver]["waiting"] == 2


FAILED = (AttentionQuery("failed", 'status = "failed"', "error"),)


def test_an_archived_top_level_job_counts_its_subtree_in_rollup_and_attention(tree):
    fleet, driver, _, _, _, cache = tree
    fleet.append(parent=driver, state=finished(1))
    snap = _archive(fleet, driver)
    rollup = cache.job_rollup(snap, {}, driver)
    assert (rollup["counts"]["waiting"], rollup["counts"]["failed"]) == (6, 1)
    summary = cache.attention.summaries(snap, {}, WAITING + FAILED)[driver]
    assert summary["attention"] == {"waiting": 6, "failed": 1}
    assert cache.tree_nodes.counts(snap, {}, driver, WAITING)[driver]["waiting"] == 6


def test_an_archived_nested_job_counts_its_subtree_but_its_parent_does_not(tree):
    fleet, driver, outer, _, _, cache = tree
    fleet.append(parent=outer, state=finished(1))
    snap = _archive(fleet, outer)
    rollup = cache.job_rollup(snap, {}, outer)
    assert (rollup["counts"]["waiting"], rollup["counts"]["failed"]) == (4, 1)
    nodes = cache.tree_nodes.counts(snap, {}, driver, WAITING + FAILED)
    assert (nodes[outer]["waiting"], nodes[outer]["failed"]) == (4, 1)
    assert (nodes[driver]["waiting"], nodes[driver]["failed"]) == (2, 0)
    summary = cache.attention.summaries(snap, {}, WAITING + FAILED)[driver]
    assert summary["attention"] == {"waiting": 2, "failed": 0}
