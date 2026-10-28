"""Plan 28 T2b: a run still running under an ended outer run is
``settled = "outlived"`` (derived, never stored) — it still counts as
running in every rollup and keeps its own children open; the index moves it
when the outer ends, when it ends itself and when a live outer goes stuck."""
import datetime

from leaderboard_fleet import T0, Fleet, finished, running
from test_settled_rollup import _count_builds, _same_as_a_fresh_build
from vmn_exp.core.query import filter_rows
from vmn_exp.core.settle import closes, counted_status, settled_as
from vmn_exp.core.status import CREATED, FAILED, RUNNING, STUCK, SUCCEEDED
from vmn_exp.core.tree import annotate_tree, fleet_summary, subtree_status, sweep_unfinished
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.status_summary import status_summary

from vmn_exp.core import status as status_mod

OUTLIVED = "outlived"


def _row(verstr, status, parent=None, **fields):
    return dict({"verstr": verstr, "status": status, "parent": parent}, **fields)


def _tree(*rows):
    return {r["verstr"]: r for r in annotate_tree(list(rows))}


class TestPure:
    def test_a_running_run_under_a_closed_parent_outlived_it(self):
        assert settled_as(RUNNING, True) == OUTLIVED
        assert settled_as(RUNNING, False) is None

    def test_it_counts_as_running_and_keeps_its_children_open(self):
        assert counted_status({"status": RUNNING, "settled": OUTLIVED}) == RUNNING
        assert closes(RUNNING, OUTLIVED) is False

    def test_an_outlived_sweep_may_still_run_its_missing_trials(self):
        row = {"status": RUNNING, "settled": OUTLIVED, "sweep_planned": 3, "sweep_trials": 1}
        assert sweep_unfinished(row) is True

    def test_every_ended_outer_settles_its_running_children(self):
        for ended in (SUCCEEDED, FAILED, STUCK):
            rows = _tree(_row("o", ended), _row("k", RUNNING, parent="o"))
            assert (rows["k"]["status"], rows["k"]["settled"]) == (RUNNING, OUTLIVED)
            assert rows["k"]["tree_status"] == RUNNING

    def test_an_open_outer_settles_none(self):
        for open_ in (RUNNING, CREATED):
            rows = _tree(_row("o", open_), _row("k", RUNNING, parent="o"))
            assert rows["k"]["settled"] is None

    def test_an_outlived_run_keeps_its_own_children_open(self):
        rows = _tree(_row("top", SUCCEEDED), _row("mid", RUNNING, parent="top"),
                     _row("leaf", CREATED, parent="mid"))
        assert (rows["mid"]["settled"], rows["leaf"]["settled"]) == (OUTLIVED, None)

    def test_a_never_started_container_passes_the_verdict_down_to_it(self):
        rows = _tree(_row("top", FAILED), _row("mid", CREATED, parent="top"),
                     _row("leaf", RUNNING, parent="mid"))
        assert (rows["mid"]["settled"], rows["leaf"]["settled"]) == ("never_started", OUTLIVED)

    def test_the_query_language_filters_on_it(self):
        rows = annotate_tree([_row("o", SUCCEEDED), _row("k0", RUNNING, parent="o"),
                              _row("k1", SUCCEEDED, parent="o")])
        assert [r["verstr"] for r in filter_rows(rows, 'settled = "outlived"')] == ["k0"]

    def test_the_status_summary_counts_it_running(self):
        body = status_summary([{"status": RUNNING, "settled": OUTLIVED}], T0)
        assert body["counts"][RUNNING] == 1 and body["total"] == 1

    def test_the_fleet_counts_it_running(self):
        states = {"a": {"state": "running", "heartbeat": "2999-01-01T00:00:00Z"}}
        fleet = fleet_summary("o", {"o": ["a"]}, states.get, closed=True)
        assert fleet["counts"][RUNNING] == 1 and fleet["lost"] == 0

    def test_one_run_reads_its_parent_to_know_it(self):
        states = {"o": {"state": "finished", "exit_code": 0},
                  "a": {"state": "running", "heartbeat": "2999-01-01T00:00:00Z"}}
        _, tree = subtree_status("a", {"a": "o"}, states.get)
        assert tree["settled"] == OUTLIVED


def _at(monkeypatch, when):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


def _settled(cache, snap):
    return {r["verstr"]: r.get("settled") for r in cache.rows(snap, archived=True)}


def _big_fleet(seed):
    fleet = Fleet(seed)
    for _ in range(100):
        fleet.append(state=finished(0))
    return fleet


def test_an_outer_that_ends_outlives_its_running_child_by_delta(monkeypatch):
    _at(monkeypatch, T0)
    fleet = _big_fleet(1)
    outer = fleet.append(state=running(T0))
    live = fleet.append(parent=outer, state=running(T0))
    fleet.append(parent=outer, state=finished(0))
    cache = LeaderboardCache()
    assert _settled(cache, fleet.snapshot())[live] is None
    builds = _count_builds(monkeypatch)

    fleet.set_state(fleet.index(outer), finished(0))
    snap = fleet.snapshot()
    rollup = cache.job_rollup(snap, {}, outer)
    assert builds == []
    assert _settled(cache, snap)[live] == OUTLIVED
    assert rollup["counts"]["running"] == 1 and rollup["lost"] == 0
    assert cache.status_summary(snap, T0)["counts"]["running"] == 1
    assert [r["verstr"] for r in cache.ordered(snap, {}, query='settled = "outlived"')] == [live]
    _same_as_a_fresh_build(cache, snap, [outer])

    fleet.set_state(fleet.index(live), finished(0))  # it ends too
    snap = fleet.snapshot()
    assert _settled(cache, snap)[live] is None
    assert cache.ordered(snap, {}, query='settled = "outlived"') == []
    _same_as_a_fresh_build(cache, snap, [outer])


def test_an_outer_that_starts_again_takes_it_back(monkeypatch):
    _at(monkeypatch, T0)
    fleet = _big_fleet(2)
    outer = fleet.append(state=finished(0))
    live = fleet.append(parent=outer, state=running(T0))
    cache = LeaderboardCache()
    assert _settled(cache, fleet.snapshot())[live] == OUTLIVED
    fleet.set_state(fleet.index(outer), running(T0))
    snap = fleet.snapshot()
    assert _settled(cache, snap)[live] is None
    _same_as_a_fresh_build(cache, snap, [outer])


def test_a_live_outer_that_goes_stuck_outlives_its_running_child(monkeypatch):
    _at(monkeypatch, T0)
    fleet = _big_fleet(3)
    later = T0 + datetime.timedelta(seconds=600)
    outer = fleet.append(state=running(T0))
    live = fleet.append(parent=outer, state=running(later))  # still beating then
    cache, snap = LeaderboardCache(), fleet.snapshot()
    assert _settled(cache, snap)[live] is None
    _at(monkeypatch, later)
    rows = {r["verstr"]: r for r in cache.rows(snap, archived=True)}
    assert rows[outer]["status"] == STUCK
    assert (rows[live]["status"], rows[live]["settled"]) == (RUNNING, OUTLIVED)
    assert cache.job_rollup(snap, {}, outer)["counts"]["running"] == 1
    _same_as_a_fresh_build(cache, snap, [outer])


def test_an_outlived_child_that_goes_stuck_is_lost(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(4)
    outer = fleet.append(state=finished(0))
    live = fleet.append(parent=outer, state=running(T0))
    cache, snap = LeaderboardCache(), fleet.snapshot()
    assert _settled(cache, snap)[live] == OUTLIVED
    _at(monkeypatch, T0 + datetime.timedelta(seconds=600))
    assert _settled(cache, snap)[live] == "lost"
