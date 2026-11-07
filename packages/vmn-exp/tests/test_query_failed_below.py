"""Plan 31 §1: ``failed_below`` (the failed and lost runs below a row) and
``failed_pct`` (their share of the runs below it, 0 without any) are query
fields, counted like the other ``*_below`` fields (stop at the nearest
archived run) and equal to the Jobs view rollup's ``failed_pct``; the board
reads them from its rollups, the core counts them only when a query reads
them."""
import pytest
from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.core import status as status_mod
from vmn_exp.core.query import filter_rows
from vmn_exp.core.query_below import below_extra
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMA = {"loss": {"goal": "min", "primary": True}}


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


@pytest.fixture
def tree():
    """An ended launch: a date with a failed, a succeeded and a lost trial,
    an archived date with a failed trial, a date that never started; and a
    healthy launch."""
    fleet = Fleet(3)
    launch = fleet.append(state=finished(0))
    date = fleet.append(parent=launch, state=finished(0))
    fleet.append(parent=date, state=finished(1))
    fleet.append(parent=date, state=finished(0))
    fleet.append(parent=date, state=running(T0, age=3600))
    shelved = fleet.append(parent=launch, state=finished(1))
    fleet.edit(fleet.index(shelved), archived=True)
    fleet.append(parent=shelved, state=finished(1))
    fleet.append(parent=shelved, state=finished(0))
    waiting = fleet.append(parent=launch)
    healthy = fleet.append(state=finished(0))
    fleet.append(parent=healthy, state=finished(0))
    return fleet, dict(launch=launch, date=date, shelved=shelved, waiting=waiting, healthy=healthy)


def _fields(extra, verstr):
    return extra["failed_below"](verstr), extra["failed_pct"](verstr)


def test_failed_below_counts_failed_and_lost_runs_up_to_the_archived_one(tree):
    fleet, v = tree
    rows = LeaderboardCache().rows(fleet.snapshot(), archived=True)
    extra = below_extra(rows)
    assert _fields(extra, v["launch"]) == (2, 40.0)  # date, 3 trials, waiting
    assert _fields(extra, v["date"]) == (2, 66.67)
    assert _fields(extra, v["shelved"]) == (1, 50.0)
    assert _fields(extra, v["waiting"]) == (0, 0.0)
    assert _fields(extra, v["healthy"]) == (0, 0.0)


def test_failed_pct_is_the_rollups(tree):
    fleet, _ = tree
    cache = LeaderboardCache()
    snap = fleet.snapshot()
    rows = cache.rows(snap, archived=True)
    extra, rollups = below_extra(rows), cache.job_rollups(snap, {})
    for row in rows:
        rolled = rollups.get(row["verstr"]) or {"failed_pct": 0.0, "counts": {}, "lost": 0}
        failed = rolled["counts"].get("failed", 0) + (rolled.get("lost") or 0)
        assert _fields(extra, row["verstr"]) == (failed, rolled["failed_pct"]), row["verstr"]


@pytest.mark.parametrize("seed", range(4))
def test_core_and_board_agree_on_failed_pct_over_generations(seed):
    fleet, cache = Fleet(seed), LeaderboardCache()
    fleet.seed(60, T0, sweeps=5, live=12)
    for _ in range(6):
        snap = fleet.snapshot()
        rows = cache.rows(snap, archived=True)
        extra, rollups = below_extra(rows), cache.job_rollups(snap, {})
        for row in rows:
            pct = (rollups.get(row["verstr"]) or {}).get("failed_pct", 0.0)
            assert extra["failed_pct"](row["verstr"]) == pct, row["verstr"]
        tops = [r for r in rows if not r["depth"] and not r.get("archived")]
        page = cache.page(snap, {}, limit=1000, top=True, top_query="failed_pct >= 5")
        core = filter_rows(tops, "failed_pct >= 5", extra=extra)
        assert sorted(r["verstr"] for r in page["rows"]) == sorted(r["verstr"] for r in core)
        fleet.mutate(T0, 15)


def test_top_q_failed_pct_keeps_the_high_failure_trees(tree):
    fleet, v = tree
    page = LeaderboardCache().page(fleet.snapshot(), SCHEMA, limit=100, top=True,
                                   top_query="failed_pct > 5")
    assert [r["verstr"] for r in page["rows"]] == [v["launch"]]


def test_a_query_not_reading_them_never_counts_them(tree, monkeypatch):
    import vmn_exp.core.query_below as query_below

    fleet, v = tree
    rows = LeaderboardCache().rows(fleet.snapshot(), archived=True)
    monkeypatch.setattr(query_below, "failed_counts", lambda rows: pytest.fail("counted"))
    extra = below_extra(rows)
    assert filter_rows(rows, "live_below >= 0", extra=extra)
    assert filter_rows(rows, 'status = "failed"', extra=extra)
