"""Plan 34 §3: a lost run (stuck, or released, under an ended outer run) is
its own state. It no longer makes its tree ``failed``: a tree whose only bad
runs are lost reads its own status, and only a run that exited with a
non-zero code below makes it ``failed`` — on every path (the core's
annotation, one run's subtree, the board's builds, its derived generations
and its live buckets)."""
import datetime

from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.core import status as status_mod
from vmn_exp.core.status import CREATED, FAILED, STUCK, SUCCEEDED
from vmn_exp.core.tree import annotate_tree, run_status
from vmn_exp.ui.leaderboard_cache import LeaderboardCache


def _row(verstr, status, parent=None):
    return {"verstr": verstr, "status": status, "parent": parent}


def _tree(*rows):
    return {r["verstr"]: r for r in annotate_tree(list(rows))}


def _at(monkeypatch, when):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


class TestAnnotate:
    def test_a_tree_whose_only_bad_runs_are_lost_reads_its_own_status(self):
        rows = _tree(_row("o", SUCCEEDED), _row("a", SUCCEEDED, "o"), _row("l", STUCK, "o"))
        assert rows["l"]["settled"] == "lost"
        assert rows["o"]["tree_status"] == SUCCEEDED

    def test_a_lost_run_adds_nothing_to_its_own_tree(self):
        rows = _tree(_row("o", SUCCEEDED), _row("l", STUCK, "o"))
        assert rows["l"]["tree_status"] is None

    def test_a_real_failure_below_still_reads_failed(self):
        rows = _tree(_row("o", SUCCEEDED), _row("f", FAILED, "o"), _row("l", STUCK, "o"))
        assert rows["o"]["tree_status"] == FAILED

    def test_lost_runs_deep_in_the_tree_read_the_tops_status(self):
        rows = _tree(_row("top", SUCCEEDED), _row("mid", CREATED, "top"),
                     _row("gone", STUCK, "mid"), _row("ok", SUCCEEDED, "top"))
        assert rows["top"]["tree_status"] == SUCCEEDED

    def test_a_failed_outer_with_lost_runs_reads_failed_by_itself(self):
        rows = _tree(_row("o", FAILED), _row("l", STUCK, "o"))
        assert rows["o"]["tree_status"] == FAILED


def test_one_runs_subtree_agrees():
    parent_of = {"a": "o", "l": "o"}
    states = {"o": finished(0), "a": finished(0), "l": running(T0, age=3600)}
    assert run_status("o", parent_of, states.get)["tree_status"] == SUCCEEDED
    lost = run_status("l", parent_of, states.get)
    assert (lost["settled"], lost["tree_status"]) == ("lost", None)


def _rows(cache, snap):
    return {r["verstr"]: r["tree_status"] for r in cache.rows(snap, archived=True)}


def _fleet():
    fleet = Fleet(7)
    for _ in range(100):  # big enough that one generation's few changes are a delta
        fleet.append(state=finished(0))
    return fleet


def test_the_board_build_reads_the_outers_own_status(monkeypatch):
    _at(monkeypatch, T0)
    fleet = _fleet()
    outer = fleet.append(state=finished(0))
    fleet.append(parent=outer, state=finished(0))
    fleet.append(parent=outer, state=running(T0, age=3600))
    assert _rows(LeaderboardCache(), fleet.snapshot())[outer] == SUCCEEDED


def test_a_derived_generation_agrees(monkeypatch):
    _at(monkeypatch, T0)
    fleet = _fleet()
    outer = fleet.append(state=running(T0))
    fleet.append(parent=outer, state=finished(0))
    fleet.append(parent=outer, state=running(T0, age=3600))
    cache = LeaderboardCache()
    assert _rows(cache, fleet.snapshot())[outer] == STUCK
    fleet.set_state(fleet.index(outer), finished(0))  # it ends: its stuck run is lost
    snap = fleet.snapshot()
    assert _rows(cache, snap)[outer] == SUCCEEDED
    assert _rows(cache, snap) == _rows(LeaderboardCache(), snap)


def test_a_live_run_that_goes_lost_between_buckets_agrees(monkeypatch):
    _at(monkeypatch, T0)
    fleet = _fleet()
    outer = fleet.append(state=finished(0))
    fleet.append(parent=outer, state=finished(0))
    fleet.append(parent=outer, state=running(T0))
    cache, snap = LeaderboardCache(), fleet.snapshot()
    assert _rows(cache, snap)[outer] == "running"
    _at(monkeypatch, T0 + datetime.timedelta(seconds=600))
    assert _rows(cache, snap)[outer] == SUCCEEDED
    assert _rows(cache, snap) == _rows(LeaderboardCache(), snap)
