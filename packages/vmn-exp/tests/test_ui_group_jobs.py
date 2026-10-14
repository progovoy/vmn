"""Plan 23 S7: a grouped Jobs view (``top=1|jobs|singles``) groups top-level
rows; each group sums its jobs' rollups: ``job_counts`` (its jobs, per tree
status), ``runs`` (the jobs' runs plus its single runs), ``failed`` (failed
or stuck among those) and ``job_aggregates`` (each job's best of the main
metric, aggregated over the group's jobs)."""
import statistics

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_group_fields import COUNT_KEYS, COUNT_OF

from vmn_exp.core import status as status_mod

SCHEMA = {"loss": {"goal": "min", "primary": True}}
FAILED = ("failed", "stuck")


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(3)
    fleet.seed_jobs(9, 40, T0, live=12)
    for _ in range(30):
        fleet.append(state=fleet.ended(T0))
    return fleet, LeaderboardCache()


def _rows(cache, snap, group, key, **params):
    return cache.groups(snap, SCHEMA, group, group_key=key, limit=5000, **params)["rows"]


def _expected(cache, snap, rows):
    summaries = cache.job_rollups(snap, SCHEMA)
    jobs = [r for r in rows if r["kind"] == "outer"]
    singles = [r for r in rows if r["kind"] != "outer"]
    counts = dict.fromkeys(COUNT_KEYS, 0)
    for job in jobs:
        counts[COUNT_OF[job["tree_status"]]] += 1
    counts["total"] = len(jobs)
    runs = sum(summaries[j["verstr"]]["total"] for j in jobs) + len(singles)
    failed = sum(sum(summaries[j["verstr"]]["counts"][s] for s in FAILED) for j in jobs)
    failed += sum(1 for s in singles if s["status"] in FAILED)
    bests = sorted(summaries[j["verstr"]]["best"] for j in jobs
                   if summaries[j["verstr"]]["best"] is not None)
    return counts, runs, failed, bests


@pytest.mark.parametrize("top", [True, "jobs", "singles"])
@pytest.mark.parametrize("group", ["branch", "status", "params.opt"])
def test_groups_of_top_level_rows_sum_their_jobs(board, top, group):
    fleet, cache = board
    snap = fleet.snapshot()
    out = cache.groups(snap, SCHEMA, group, top=top)
    assert out["groups"]
    for g in out["groups"]:
        rows = _rows(cache, snap, group, g["key"], top=top)
        counts, runs, failed, bests = _expected(cache, snap, rows)
        assert g["job_counts"] == counts
        assert (g["runs"], g["failed"]) == (runs, failed)
        if not bests:
            assert g["job_aggregates"] == {}
            continue
        agg = g["job_aggregates"]["loss"]
        assert agg["n"] == len(bests)
        assert agg["min"] == bests[0] and agg["max"] == bests[-1]
        assert agg["best"] == bests[0]  # loss: lower is better
        assert agg["median"] == statistics.median(bests)
        assert agg["mean"] == pytest.approx(statistics.fmean(bests))


def test_a_jobs_group_counts_every_run_under_its_jobs(board):
    fleet, cache = board
    out = cache.groups(fleet.snapshot(), SCHEMA, "status", top="jobs")
    assert sum(g["job_counts"]["total"] for g in out["groups"]) == 9
    assert sum(g["runs"] for g in out["groups"]) == 9 * 40


def test_groups_without_top_carry_no_job_fields(board):
    fleet, cache = board
    group = cache.groups(fleet.snapshot(), SCHEMA, "branch")["groups"][0]
    assert not {"job_counts", "runs", "failed", "job_aggregates"} & set(group)


def test_a_paged_group_carries_the_job_fields_too(board):
    fleet, cache = board
    snap = fleet.snapshot()
    key = cache.groups(snap, SCHEMA, "branch", top=True)["groups"][0]["key"]
    page = cache.groups(snap, SCHEMA, "branch", top=True, group_key=key)
    assert {"job_counts", "runs", "failed", "job_aggregates"} <= set(page)


def test_job_fields_follow_new_generations(board):
    fleet, cache = board
    for _ in range(6):
        fleet.mutate(T0, 5, reparent=False)
        snap = fleet.snapshot()
        got = cache.groups(snap, SCHEMA, "branch", top=True)["groups"]
        fresh = LeaderboardCache().groups(snap, SCHEMA, "branch", top=True)["groups"]
        fields = ("key", "job_counts", "runs", "failed", "job_aggregates")
        assert [[g[f] for f in fields] for g in got] == [[g[f] for f in fields] for g in fresh]
