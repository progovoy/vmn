"""Plan 23 S2: the Jobs view, ``top=1``: top-level rows only, each with
``job`` (its compact rollup, null for a single run) and ``job:*`` sorts over
those summaries."""
import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.core import status as status_mod
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMA = {"loss": {"goal": "min", "primary": True}}
FIELDS = {"total", "counts", "done", "expected", "progress", "failed_pct",
          "throughput_per_min", "eta_sec", "metric", "best", "best_verstr", "best_idx", "spread"}


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(11)
    jobs = fleet.seed_jobs(4, 30, T0, live=10)
    singles = [fleet.append(state=fleet.ended(T0)) for _ in range(5)]
    # job 2 has a nested job: its rollup covers the nested job's runs too
    nested = fleet.append(parent=jobs[2])
    for _ in range(3):
        fleet.append(parent=nested, state=fleet.ended(T0, code=1))
    return fleet, jobs, singles, LeaderboardCache()


def _page(cache, snap, **params):
    return cache.page(snap, SCHEMA, limit=100, top=True, **params)


def test_top_rows_are_the_top_level_runs_with_their_job(board):
    fleet, jobs, singles, cache = board
    snap = fleet.snapshot()
    page = _page(cache, snap)
    assert page["total"] == len(jobs) + len(singles)
    rows = {r["verstr"]: r for r in page["rows"]}
    assert set(rows) == set(jobs) | set(singles)
    summaries = cache.job_rollups(snap, SCHEMA)
    for job in jobs:
        assert FIELDS <= set(rows[job]["job"])
        assert rows[job]["job"]["total"] == summaries[job]["total"]
    assert all(rows[s]["job"] is None for s in singles)
    assert rows[jobs[2]]["job"]["total"] == 30 + 1 + 3


def test_best_idx_is_the_best_runs_idx(board):
    fleet, jobs, _, cache = board
    snap = fleet.snapshot()
    by_verstr = {r["verstr"]: r for r in cache.rows(snap)}
    for row in _page(cache, snap)["rows"]:
        job = row["job"]
        if job and job["best_verstr"]:
            assert job["best_idx"] == by_verstr[job["best_verstr"]]["idx"]


@pytest.mark.parametrize("sort,field", [
    ("job:progress", "progress"), ("job:failed_pct", "failed_pct"), ("job:total", "total"),
    ("job:throughput", "throughput_per_min"), ("job:started", "started_at")])
def test_job_sorts_rank_jobs_most_first_singles_last(board, sort, field):
    fleet, jobs, singles, cache = board
    snap = fleet.snapshot()
    rows = _page(cache, snap, sort=sort)["rows"]
    values = [r["job"][field] for r in rows[:len(jobs)]]
    assert values == sorted(values, reverse=True)
    assert {r["verstr"] for r in rows[len(jobs):]} == set(singles)
    asc = [r["job"][field] for r in _page(cache, snap, sort=sort, order="asc")["rows"][:len(jobs)]]
    assert asc == sorted(values)


def test_job_best_is_best_first_by_the_goal(board):
    fleet, jobs, _, cache = board
    rows = _page(cache, fleet.snapshot(), sort="job:best")["rows"][:len(jobs)]
    best = [r["job"]["best"] for r in rows]
    assert best == sorted(best)  # loss: lower is better


def test_q_and_status_filter_the_top_rows_by_their_own_fields(board):
    fleet, jobs, singles, cache = board
    snap = fleet.snapshot()
    assert {r["verstr"] for r in _page(cache, snap, status="running")["rows"]} == set(jobs)
    assert _page(cache, snap, query='kind = "single"')["total"] == len(singles)
    page = _page(cache, snap, sort="job:failed_pct", query='kind = "outer"')
    assert {r["verstr"] for r in page["rows"]} == set(jobs)


def test_a_job_sort_without_top_is_refused(board):
    fleet, _, _, cache = board
    with pytest.raises(ValueError):
        cache.page(fleet.snapshot(), SCHEMA, limit=10, sort="job:progress")


def test_without_top_rows_carry_no_job(board):
    fleet, _, _, cache = board
    rows = cache.page(fleet.snapshot(), SCHEMA, limit=10)["rows"]
    assert all("job" not in r for r in rows)
