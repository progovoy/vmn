"""Plan 11 §4.6: a workspace's cache heals itself without a restart. A
detected problem (or ``resync(full=True)``) rebuilds in the background into
a new SQLite file swapped in by rename while the live indexes keep serving;
a plain ``resync()`` re-checks every record's signature."""
import os
import threading

import pytest

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.ui import cache_resync
from vmn_exp.ui.cache_health import SqliteHealth
from vmn_exp.ui.cache_resync import WorkspaceCache

APP = "app"
FINISHED = "state: finished\nexit_code: 0\n"


@pytest.fixture
def st(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "cache.sqlite")


def _make(st, i):
    verstr = f"0.0.1-dev.abc.r{i}"
    st.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
    st.save_file(APP, verstr, "run_state.yml", FINISHED)
    return verstr


def _setup(st, path, runs=3):
    verstrs = {_make(st, i) for i in range(runs)}
    index = ExperimentIndex(st, APP, cache_path=path).refresh()
    cache = WorkspaceCache("ws", path, SqliteHealth(path), check_sec=0)
    cache.note(APP, st, lambda: index)
    return index, cache, verstrs


def _verstrs(index):
    return {r["verstr"] for r in index.rows()}


def test_a_deleted_cache_is_rebuilt_in_the_background(st, path):
    index, cache, verstrs = _setup(st, path)
    os.remove(path)
    cache.tick()
    assert cache.wait(10)
    assert set(SqliteStore(path).load(APP)) == verstrs
    assert _verstrs(index) == verstrs
    status = cache.status()
    assert status["state"] == "idle" and status["last_rebuild_reason"] == "missing"
    assert status["progress"] == {"done": 3, "total": 3}
    assert cache.tick() is None and status["rebuilds"] == 1


def test_a_healthy_cache_is_left_alone(st, path):
    _, cache, _ = _setup(st, path)
    cache.tick()
    assert cache.status()["rebuilds"] == 0


def test_a_full_resync_swaps_a_new_file_in_by_rename(st, path):
    index, cache, verstrs = _setup(st, path)
    swapped = []
    cache.on_swapped(lambda: swapped.append(os.stat(path).st_ino))
    before = os.stat(path).st_ino
    cache.resync(full=True)
    assert cache.wait(10)
    assert swapped and swapped[0] != before
    new = _make(st, 9)
    index.hint(new)
    index.refresh()
    assert new in set(SqliteStore(path).load(APP))
    assert cache.tick() is None and cache.status()["rebuilds"] == 1


def test_requests_keep_being_served_during_a_rebuild(st, path, monkeypatch):
    index, cache, verstrs = _setup(st, path)
    gate = threading.Event()
    real = cache_resync._build

    def slow(*args):
        gate.wait(10)
        return real(*args)

    monkeypatch.setattr(cache_resync, "_build", slow)
    cache.resync(full=True)
    assert cache.status()["state"] == "rebuilding"
    assert _verstrs(index.refresh()) == verstrs
    gate.set()
    assert cache.wait(10)
    assert cache.status()["state"] == "idle"


def test_a_plain_resync_rechecks_every_record(st, path):
    index, cache, verstrs = _setup(st, path)
    index.journaled, index.full_sweep_sec = True, 3600
    index.refresh()
    new = _make(st, 7)
    index.refresh()
    assert new not in _verstrs(index)
    cache.resync()
    index.refresh()
    assert new in _verstrs(index)
    assert cache.status()["rebuilds"] == 0


def test_status_reports_generation_drift_and_reconcile(st, path):
    index, cache, _ = _setup(st, path)
    status = cache.status()
    app = status["apps"][APP]
    assert app["generation"] == index.generation and app["records"] == 3
    assert status["drift"] == 0 and app["last_reconcile_at"] is not None
    assert status["journal_lag_sec"] is None
