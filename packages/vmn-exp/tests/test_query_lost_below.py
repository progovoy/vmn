"""Plan 34 §3: ``lost_below`` (the lost runs below a row) is a query field,
counted like the other ``*_below`` fields (stop at the nearest archived
run), the board reading it from its rollups' ``lost``; ``failed_below`` and
``failed_pct`` keep counting lost runs."""
import pytest
from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.core import status as status_mod
from vmn_exp.core.query import BELOW_FIELDS, filter_rows
from vmn_exp.core.query_below import below_extra
from vmn_exp.ui.leaderboard_cache import LeaderboardCache


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _lost():
    return running(T0, age=3600)


@pytest.fixture
def tree():
    """An ended launch: a date with a succeeded and two lost trials, an
    archived date with a lost trial; a launch with a real failure only."""
    fleet = Fleet(5)
    launch = fleet.append(state=finished(0))
    date = fleet.append(parent=launch, state=finished(0))
    fleet.append(parent=date, state=finished(0))
    fleet.append(parent=date, state=_lost())
    fleet.append(parent=date, state=_lost())
    shelved = fleet.append(parent=launch, state=finished(0))
    fleet.edit(fleet.index(shelved), archived=True)
    fleet.append(parent=shelved, state=_lost())
    failing = fleet.append(state=finished(0))
    fleet.append(parent=failing, state=finished(1))
    return fleet, dict(launch=launch, date=date, shelved=shelved, failing=failing)


def test_lost_below_is_a_below_field():
    assert "lost_below" in BELOW_FIELDS


def test_lost_below_counts_the_lost_runs_up_to_the_archived_one(tree):
    fleet, v = tree
    extra = below_extra(LeaderboardCache().rows(fleet.snapshot(), archived=True))
    counts = {k: extra["lost_below"](verstr) for k, verstr in v.items()}
    assert counts == dict(launch=2, date=2, shelved=1, failing=0)


def test_failed_below_keeps_counting_the_lost_runs(tree):
    fleet, v = tree
    extra = below_extra(LeaderboardCache().rows(fleet.snapshot(), archived=True))
    assert (extra["failed_below"](v["launch"]), extra["failed_pct"](v["launch"])) == (2, 50.0)


def test_the_board_reads_the_rollups_lost(tree):
    fleet, _ = tree
    cache, snap = LeaderboardCache(), fleet.snapshot()
    rows = cache.rows(snap, archived=True)
    extra, rollups = below_extra(rows), cache.job_rollups(snap, {})
    for row in rows:
        lost = (rollups.get(row["verstr"]) or {}).get("lost") or 0
        assert extra["lost_below"](row["verstr"]) == lost, row["verstr"]


def test_top_q_lost_below_keeps_the_trees_with_lost_runs(tree):
    fleet, v = tree
    page = LeaderboardCache().page(fleet.snapshot(), {}, limit=100, top=True,
                                   top_query="lost_below > 0")
    assert [r["verstr"] for r in page["rows"]] == [v["launch"]]


@pytest.mark.parametrize("seed", range(3))
def test_core_and_board_agree_over_generations(seed):
    fleet, cache = Fleet(seed), LeaderboardCache()
    fleet.seed(60, T0, sweeps=5, live=12)
    for _ in range(5):
        snap = fleet.snapshot()
        rows = cache.rows(snap, archived=True)
        tops = [r for r in rows if not r["depth"] and not r.get("archived")]
        page = cache.page(snap, {}, limit=1000, top=True, top_query="lost_below > 0")
        core = filter_rows(tops, "lost_below > 0", extra=below_extra(rows))
        assert sorted(r["verstr"] for r in page["rows"]) == sorted(r["verstr"] for r in core)
        fleet.mutate(T0, 15)
