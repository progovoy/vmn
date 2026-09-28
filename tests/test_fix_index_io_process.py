"""Scale guard: a server's index refresh must not do its filesystem work on
the server's own threads.

Every ``stat``/``open``/``scandir`` (and each SQLite row step) releases the
GIL, and getting it back from a busy request thread costs up to the switch
interval (5ms). At 100k records a refresh makes ~100k such calls, so under
request load one refresh took minutes and new runs never showed up. With
``use_io_process()`` the listing, the reads and the persistence run in a
helper process; the index process only exchanges a few pickles with it.
Counts calls instead of timing, so it cannot flake.
"""
import builtins
import os
import sqlite3

import pytest

from vmn_exp.core import index as experiment_index
from vmn_exp.core.index import ExperimentIndex

from test_fix_index_refresh_scale import (  # noqa: F401  (fixtures)
    APP, M, N, Store, _churn, _now_iso, clock, live_store,
)

FULL_SWEEP_SEC = 300
_FS_CALLS = ("stat", "lstat", "scandir", "listdir", "open")


@pytest.fixture
def fs_calls(monkeypatch):
    """Filesystem and SQLite calls made in this process while ``calls["on"]``."""
    calls = {"on": False, "n": []}

    def wrap(owner, name):
        real = getattr(owner, name)

        def counted(*args, **kwargs):
            if calls["on"]:
                calls["n"].append((name, args[:1]))
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, name, counted)

    for name in _FS_CALLS:
        wrap(os, name)
    wrap(builtins, "open")
    wrap(sqlite3, "connect")
    return calls


@pytest.fixture
def offloaded(live_store, tmp_path):
    index = ExperimentIndex(live_store.st, APP, cache_path=str(tmp_path / "idx.sqlite"),
                            full_sweep_sec=FULL_SWEEP_SEC)
    assert index.use_io_process()
    yield index
    index.close()


def test_a_refresh_makes_no_filesystem_calls_in_the_index_process(
    offloaded, live_store, clock, fs_calls
):
    fs_calls["on"] = True
    offloaded.refresh()  # the cold load too: listing, reads and SQLite
    for cycle in range(1, 4):
        fs_calls["on"] = False
        _churn(live_store, cycle)
        new = live_store.add(N + M + cycle, f"state: running\nheartbeat: '{_now_iso()}'\n")
        clock.now += 1 if cycle < 3 else FULL_SWEEP_SEC + 1  # the last one sweeps fully
        fs_calls["on"] = True
        offloaded.refresh()
        fs_calls["on"] = False
        snap = offloaded.snapshot()
        assert snap.row(new) is not None  # listed after one refresh despite the churn
        assert all(snap.row(v)["metrics"]["loss"] == cycle for v in live_store.live)
    assert fs_calls["n"] == []


def test_the_rows_match_a_direct_read(offloaded, live_store, clock):
    offloaded.refresh()
    for cycle in range(1, 4):
        _churn(live_store, cycle)
        live_store.st.delete(APP, live_store.live.pop())
        live_store.add(N + M + cycle, "state: finished\nexit_code: 1\n")
        clock.now += 1 if cycle < 3 else FULL_SWEEP_SEC + 1
        offloaded.refresh()
    rows, states = experiment_index.direct_rows(live_store.st, APP)
    snap = offloaded.snapshot()
    assert [dict(r) for r in snap.rows] == rows
    assert snap.run_states == states


def test_the_helper_persists_what_a_restart_loads(offloaded, live_store, clock, tmp_path):
    offloaded.refresh()
    _churn(live_store, 1)
    clock.now += 1
    offloaded.refresh()
    offloaded.close()

    warm = ExperimentIndex(live_store.st, APP, cache_path=str(tmp_path / "idx.sqlite"),
                           full_sweep_sec=FULL_SWEEP_SEC)
    warm_records = warm._store.load(APP)
    assert len(warm_records) == N + M
    assert all(warm_records[v]["fold"]["metrics"]["loss"][0] == 1 for v in live_store.live)


def test_unchanged_records_keep_their_row_and_run_state_objects(offloaded, live_store, clock):
    offloaded.refresh()
    before = offloaded.snapshot()
    _churn(live_store, 1)
    clock.now += 1
    offloaded.refresh()
    after = offloaded.snapshot()
    quiet = [r["verstr"] for r in before.rows if r["verstr"] not in live_store.live]
    assert all(after.row(v) is before.row(v) for v in quiet)
    assert all(after.run_states[v] is before.run_states[v] for v in quiet)
    assert all(after.row(v) is not before.row(v) for v in live_store.live)


def test_a_dead_helper_is_replaced(offloaded, live_store, clock):
    offloaded.refresh()
    offloaded._io.kill_for_tests()
    _churn(live_store, 1)
    clock.now += 1
    with pytest.raises(experiment_index.IOProcessError):
        offloaded.refresh()  # the refresh that meets the dead helper fails whole
    offloaded.refresh()
    assert all(offloaded.snapshot().row(v)["metrics"]["loss"] == 1 for v in live_store.live)


def test_storage_the_helper_cannot_read_stays_in_process(tmp_path):
    class Subclassed(Store(str(tmp_path)).st.__class__):
        pass

    index = ExperimentIndex(Subclassed(str(tmp_path), subdir="experiments"), APP)
    assert not index.use_io_process()
    index.refresh()


def test_the_helper_sweeps_a_slice_per_refresh_never_everything_at_once(
    offloaded, live_store, clock, monkeypatch
):
    """A full listing of 100k records keeps one refresh busy for seconds; the
    helper re-lists known records a time-proportional slice per refresh, so
    each is still seen within full_sweep_sec (an in-place edit of a finished
    run, which no directory signature shows, is caught by it)."""
    offloaded.refresh()
    watch = offloaded._io.watch
    fulls, slices = [], []
    for name, sink in (("full_changes", fulls), ("slice_changes", slices)):
        real = getattr(watch, name)
        monkeypatch.setattr(watch, name, lambda *a, real=real, sink=sink: (sink.append(a), real(*a))[1])
    quiet = next(r["verstr"] for r in offloaded.snapshot().rows if r["verstr"] not in live_store.live)
    live_store.log(quiet, 7)  # an append leaves the directory signature alone

    step = FULL_SWEEP_SEC / 10
    for _ in range(11):
        clock.now += step
        offloaded.refresh()

    assert fulls == []
    total = N + M
    assert all(len(keys) <= total / 10 + 1 for (keys,) in slices)
    assert sum(len(keys) for (keys,) in slices) >= total
    assert offloaded.snapshot().row(quiet)["metrics"]["loss"] == 7


def test_a_slow_refresh_does_not_make_the_next_one_sweep_everything(
    offloaded, live_store, clock, monkeypatch
):
    """A cold load can take longer than full_sweep_sec; the refresh after it
    still lists only a slice, not every record at once."""
    offloaded.refresh()
    watch = offloaded._io.watch
    slices = []
    real = watch.slice_changes
    monkeypatch.setattr(watch, "slice_changes", lambda keys: slices.append(keys) or real(keys))
    clock.now += 5 * FULL_SWEEP_SEC
    offloaded.refresh()
    assert slices and all(len(keys) <= (N + M) / 10 + 1 for keys in slices)
