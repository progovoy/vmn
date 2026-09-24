"""IndexSnapshot: an immutable, lock-free view of the index per generation;
heartbeats neither drop cached rows nor rewrite persisted records."""
import dataclasses
import sqlite3
import threading
import time

import pytest

from version_stamp.cli.snapshot import LocalSnapshotStorage, _resolve_verstr
from version_stamp.core import experiment_index
from version_stamp.core.experiment_index import (
    ExperimentIndex,
    direct_rows,
    indexed_snapshot,
    indexed_status_rows,
)
from version_stamp.core.experiment_index_snapshot import IndexSnapshot

APP = "app"


@pytest.fixture
def st(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "repo"), subdir="experiments")


def _make(st, name, second, parent=None, run_state=None):
    verstr = f"0.0.1-dev.{name}"
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{second:02d}Z",
            "parent": parent}
    st.save(APP, verstr, meta, {})
    st.append_log_entry(APP, verstr, "w", {"timestamp": "t", "type": "create",
                                            "note": f"note {name}"})
    if run_state is not None:
        st.save_file(APP, verstr, "run_state.yml", run_state)
    return verstr


def _seed(st):
    a = _make(st, "abc.r1", 1, run_state="state: running\n")
    b = _make(st, "abd.r2", 2, parent=a)
    c = _make(st, "xyz.r3", 3, run_state="state: finished\nexit_code: 0\n")
    return a, b, c


def _index(st, tmp_path):
    return ExperimentIndex(st, APP, cache_path=str(tmp_path / "idx.sqlite"))


def test_snapshot_holds_rows_states_and_edges(st, tmp_path):
    a, b, c = _seed(st)
    index = _index(st, tmp_path).refresh()
    snap = index.snapshot()

    assert isinstance(snap, IndexSnapshot)
    assert isinstance(snap.rows, tuple)
    assert list(snap.rows) == index.rows()
    assert snap.run_states == index.run_states()
    assert snap.edges == {a: None, b: a, c: None}
    assert snap.row(b)["idx"] == 2
    assert snap.row("0.0.1-dev.nope") is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.generation = 99


def test_rows_with_create_note_still_work(st, tmp_path):
    _seed(st)
    index = _index(st, tmp_path).refresh()
    assert [r["create_note"] for r in index.rows(True)] == [
        "note abc.r1", "note abd.r2", "note xyz.r3"]
    assert "create_note" not in index.rows()[0]


def test_generation_bumps_only_on_visible_change(st, tmp_path):
    a, _, _ = _seed(st)
    index = _index(st, tmp_path).refresh()
    first = index.snapshot()

    index.refresh()
    assert index.generation == first.generation
    assert index.snapshot() is first

    st.save_file(APP, a, "run_state.yml", "state: running\nheartbeat: '2026-01-02T00:00:00Z'\n")
    index.refresh()
    snap = index.snapshot()
    assert index.generation == snap.generation > first.generation
    assert snap.run_states[a]["heartbeat"] == "2026-01-02T00:00:00Z"


def test_a_heartbeat_keeps_cached_rows_and_persisted_records(st, tmp_path):
    a, _, _ = _seed(st)
    path = str(tmp_path / "idx.sqlite")
    index = _index(st, tmp_path).refresh()
    before = index.snapshot()
    persisted = sqlite3.connect(path).execute(
        "SELECT key, data FROM exp_index ORDER BY key").fetchall()

    st.save_file(APP, a, "run_state.yml", "state: running\nheartbeat: '2026-01-02T00:00:00Z'\n")
    index.refresh()

    after = index.snapshot()
    assert all(x is y for x, y in zip(before.rows, after.rows))
    assert sqlite3.connect(path).execute(
        "SELECT key, data FROM exp_index ORDER BY key").fetchall() == persisted
    # ...and the new state is persisted on its own: a new process sees it.
    warm = _index(st, tmp_path).refresh()
    assert warm.run_states()[a]["heartbeat"] == "2026-01-02T00:00:00Z"


@pytest.mark.parametrize("ref", [
    "@1", "@3", "@0", "@4", "@x", "latest", "@latest", "0.0.1-dev.abc.r1",
    "0.0.1-dev.ab", "0.0.1-dev.abd", "0.0.1-dev.q", "1.2.3", None,
])
def test_resolve_matches_the_cli(st, tmp_path, ref):
    _seed(st)
    snap = _index(st, tmp_path).refresh().snapshot()
    for kind in ("experiment", "snapshot"):
        assert snap.resolve(ref, kind=kind) == _resolve_verstr(st, APP, ref, kind=kind)


def test_resolve_latest_flag_and_empty_index(st, tmp_path):
    _, _, c = _seed(st)
    snap = _index(st, tmp_path).refresh().snapshot()
    assert snap.resolve(None, latest=True) == (c, None)

    empty = ExperimentIndex(LocalSnapshotStorage(str(tmp_path / "e")), APP).snapshot()
    assert empty.resolve("latest", kind="experiment") == (
        None, "No experiments found for app")


def test_reading_a_snapshot_touches_neither_lock_nor_storage(st, tmp_path, monkeypatch):
    a, _, _ = _seed(st)
    index = _index(st, tmp_path).refresh()
    snap = index.snapshot()

    def boom(*args, **kwargs):
        raise AssertionError("storage touched")

    for name in ("list_files", "list_record_names", "load_file", "exists",
                 "list_snapshots", "list_verstrs"):
        monkeypatch.setattr(st, name, boom)

    done = []

    def read():
        s = index.snapshot()
        done.append((s.resolve("0.0.1-dev.ab"), s.resolve("@1"), s.row(a)["idx"],
                     len(index.rows()), len(index.run_states())))

    with index._lock:  # held as if a slow refresh were running
        reader = threading.Thread(target=read)
        reader.start()
        reader.join(2)
    assert done and done[0][1] == (a, None)
    assert snap is index.snapshot()


def test_refresh_if_stale_skips_a_fresh_index(st, tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(experiment_index, "_monotonic", lambda: clock[0])
    a, _, _ = _seed(st)
    index = _index(st, tmp_path)
    assert index.last_refresh_at is None

    first = index.refresh_if_stale(5)
    assert index.last_refresh_at == 100.0
    st.save_file(APP, a, "run_state.yml", "state: running\nheartbeat: 'x'\n")

    clock[0] += 4
    assert index.refresh_if_stale(5) is first
    clock[0] += 2
    assert index.refresh_if_stale(5).run_states[a]["heartbeat"] == "x"
    assert index.last_refresh_at == 106.0


def test_refresh_if_stale_does_not_wait_for_another_refresh(st, tmp_path):
    _seed(st)
    index = _index(st, tmp_path)
    first = index.refresh_if_stale(0)

    with index._lock:
        start = time.monotonic()
        assert index.refresh_if_stale(0) is first
        assert time.monotonic() - start < 1


def test_the_first_load_waits_for_a_running_refresh(st, tmp_path):
    _seed(st)
    index = _index(st, tmp_path)
    got = []
    with index._lock:
        reader = threading.Thread(target=lambda: got.append(index.refresh_if_stale(60)))
        reader.start()
        reader.join(0.2)
        assert got == []  # blocked behind the lock
    reader.join(5)
    assert len(got[0].rows) == 3


def test_indexed_snapshot_matches_a_direct_read(st, tmp_path):
    _seed(st)
    cache = str(tmp_path / "shared.sqlite")
    snap = indexed_snapshot(st, APP, cache_path=cache)
    rows, states = direct_rows(st, APP)
    assert list(snap.rows) == rows
    assert snap.run_states == states


def test_indexed_status_rows_are_copies_of_the_snapshot(st, tmp_path):
    _seed(st)
    cache = str(tmp_path / "shared.sqlite")
    snap = indexed_snapshot(st, APP, cache_path=cache)
    rows, states, observed = indexed_status_rows(
        st, APP, with_create_note=True, cache_path=cache
    )
    assert rows == direct_rows(st, APP, with_create_note=True)[0]
    assert states == snap.run_states
    assert observed == snap.run_state_observed_at
    rows[0]["verstr"] = "changed"
    assert snap.rows[0]["verstr"] != "changed"


def test_indexed_snapshot_waits_for_a_refresh_when_asked(st, tmp_path):
    _seed(st)
    cache = str(tmp_path / "shared.sqlite")
    index = experiment_index.shared_index(st, APP, cache)
    index.refresh()
    _make(st, "def.r9", 9)
    with index._lock:
        # Another thread's refresh holds the lock: a stale-read returns the
        # current snapshot at once; a waiting read would block.
        assert len(indexed_snapshot(st, APP, cache_path=cache).rows) == 3
    assert len(indexed_snapshot(st, APP, cache_path=cache, wait=True).rows) == 4


def test_indexed_snapshot_falls_back_to_a_direct_read(st, monkeypatch):
    a, _, _ = _seed(st)

    def broken(*args, **kwargs):
        raise RuntimeError("no index")

    monkeypatch.setattr(experiment_index, "shared_index", broken)
    snap = indexed_snapshot(st, APP)
    assert [r["verstr"] for r in snap.rows] == [r["verstr"] for r in direct_rows(st, APP)[0]]
    assert indexed_snapshot(st, APP, fallback=None) is None
    assert indexed_status_rows(st, APP)[0] == direct_rows(st, APP)[0]
    assert snap.resolve("@1") == (a, None)
