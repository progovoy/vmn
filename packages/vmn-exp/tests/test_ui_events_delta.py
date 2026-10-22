"""ui.live_events at scale: a generation's diff reads the index's own delta
(rows found by slot identity) instead of looking every run up, and the
memos keep only the last couple of snapshots alive; the search indexes are
kept per app, so one app's generations never evict another's."""
import datetime
import gc
import weakref

from test_ui_events import _next, _row, _running, _snap
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.ui.live_events import live_change, snapshot_change
from vmn_exp.ui.search_index import SearchIndexes


def _counting_lookups(monkeypatch):
    calls = []
    real = IndexSnapshot.row
    monkeypatch.setattr(IndexSnapshot, "row", lambda self, v: calls.append(v) or real(self, v))
    return calls


def test_a_small_change_looks_up_only_the_rows_it_touched(monkeypatch):
    old = _snap([_row(f"r{i}") for i in range(3000)])
    new = _next(old, changed=["r17"], added=[_row("x", "r5")])
    calls = _counting_lookups(monkeypatch)

    assert snapshot_change(old, new) == {"rows": 2, "jobs": ["r17", "r5"]}
    assert len(calls) < 20


def test_a_removed_row_in_the_middle_is_the_only_change():
    old = _snap([_row("a"), _row("b"), _row("c"), _row("d", "c")])
    new = _next(old, removed=["b"])

    assert snapshot_change(old, new) == {"rows": 1, "jobs": ["b"]}


def test_a_store_time_change_alone_moves_nothing_but_a_run_state_does():
    rows = [_row("a"), _row("b")]
    states = {"a": {"exit_code": None}, "b": {"exit_code": None}}
    old = IndexSnapshot.build("app", 1, rows, states, observed_at={"a": 1, "b": 1})
    seen = IndexSnapshot.build("app", 2, rows, dict(states), observed_at={"a": 2, "b": 2})
    new = IndexSnapshot.build("app", 3, rows, dict(states, b={"exit_code": 0}))

    assert snapshot_change(old, seen) == {"rows": 0, "jobs": []}
    assert snapshot_change(seen, new) == {"rows": 1, "jobs": ["b"]}


def test_old_snapshots_are_not_kept_alive():
    snaps = [_snap([_row("a"), _row("b")], {"a": {"exit_code": None}})]
    for _ in range(4):
        snaps.append(_next(snaps[-1], changed=["a"]))
    for old, new in zip(snaps, snaps[1:]):
        snapshot_change(old, new)
        live_change(new, "top")
        live_change(new, "a")
    first = weakref.ref(snaps[0])
    del snaps[:2], old, new
    gc.collect()

    assert first() is None


def test_live_runs_of_a_scope_follow_the_snapshot():
    snap = _snap([_row("a"), _row("a1", "a"), _row("b"), _row("c")],
                 {"a1": _running(), "b": _running()})
    assert live_change(snap, "a") == {"rows": 1, "jobs": ["a"]}
    assert live_change(snap) == {"rows": 2, "jobs": ["a", "b"]}
    assert live_change(snap, "c") is None


def test_one_apps_generations_do_not_evict_another_apps_index():
    indexes = SearchIndexes()
    a = IndexSnapshot.build("a", 1, [_row("x")], {})
    first = indexes.get(a)
    for generation in range(2, 6):
        indexes.get(IndexSnapshot.build("b", generation, [_row("y")], {}))

    assert indexes.get(a) is first


def _beating(seconds_ago):
    at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds_ago)
    return at, {"state": "running", "exit_code": None, "heartbeat_interval_sec": 30,
                "heartbeat": at.strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_a_stuck_run_is_not_live_but_a_fresh_running_one_is():
    stale_at, stale = _beating(3600)
    fresh_at, fresh = _beating(0)
    stuck = IndexSnapshot.build("app", 1, [_row("a")], {"a": stale},
                                observed_at={"a": stale_at})
    running = IndexSnapshot.build("app", 2, [_row("a")], {"a": fresh},
                                  observed_at={"a": fresh_at})

    assert live_change(stuck) is None
    assert live_change(running) == {"rows": 1, "jobs": ["a"]}
