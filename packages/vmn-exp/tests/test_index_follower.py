"""Follower mode: an ExperimentIndex fed only by a shared CacheStore's
``load_since`` deltas builds the same snapshots as the leader."""
import random

import pytest

from vmn_exp.core import index_store
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
FIELDS = ("rows", "run_states", "edges", "create_notes", "run_state_observed_at",
          "metric_parts", "outputs", "declared_defs")


@pytest.fixture
def st(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "cache.sqlite")


def _verstr(i):
    return f"0.0.1-dev.abc.r{i}"


def _make(st, i, rng):
    verstr = _verstr(i)
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:{rng.randrange(60):02d}:00Z",
            "note": f"n{i}"}
    st.save(APP, verstr, meta, {})
    _log(st, i, rng)


def _log(st, i, rng):
    st.append_log_entry(APP, _verstr(i), "w", {
        "timestamp": "t", "type": "metrics", "values": {"loss": rng.random()}})


def _state(st, i, rng):
    state = rng.choice(["state: running\n", "state: finished\nexit_code: 0\n"])
    st.save_file(APP, _verstr(i), "run_state.yml", state)


def _equal(leader, follower):
    for name in FIELDS:
        assert getattr(follower, name) == getattr(leader, name), name


class RaisingStorage:
    """Any storage access fails the test."""

    def __getattr__(self, name):
        pytest.fail(f"follower touched storage: {name}")


def test_follower_never_touches_storage(st, db, monkeypatch):
    _make(st, 0, random.Random(0))
    ExperimentIndex(st, APP, cache_path=db).refresh()
    monkeypatch.setattr(ExperimentIndex, "_refresh_from_storage",
                        lambda *a: pytest.fail("follower refreshed from storage"))
    follower = ExperimentIndex.follower(SqliteStore(db), APP)
    follower._storage = RaisingStorage()
    assert [r["verstr"] for r in follower.refresh().snapshot().rows] == [_verstr(0)]


@pytest.mark.parametrize("seed", range(4))
def test_follower_matches_leader_after_each_change(st, db, seed):
    rng = random.Random(seed)
    leader = ExperimentIndex(st, APP, cache_path=db)
    follower = ExperimentIndex.follower(SqliteStore(db), APP)
    live, next_i = set(), 0
    for _ in range(25):
        op = rng.choice(["new", "new", "log", "state", "note", "delete"])
        if op == "new" or not live:
            _make(st, next_i, rng)
            live.add(next_i)
            next_i += 1
        else:
            i = rng.choice(sorted(live))
            if op == "log":
                _log(st, i, rng)
            elif op == "state":
                _state(st, i, rng)
            elif op == "note":
                st.update_note(APP, _verstr(i), f"note {rng.random()}")
            else:
                st.delete(APP, _verstr(i))
                live.discard(i)
        _equal(leader.refresh().snapshot(), follower.refresh().snapshot())


def test_removal_and_state_only_changes_propagate(st, db):
    rng = random.Random(1)
    leader = ExperimentIndex(st, APP, cache_path=db)
    follower = ExperimentIndex.follower(SqliteStore(db), APP)
    for i in range(3):
        _make(st, i, rng)
    leader.refresh()
    assert len(follower.refresh().snapshot().rows) == 3
    gen = follower.generation

    st.save_file(APP, _verstr(1), "run_state.yml", "state: finished\nexit_code: 3\n")
    leader.refresh()
    snap = follower.refresh().snapshot()
    assert snap.run_states[_verstr(1)]["exit_code"] == 3
    assert follower.generation > gen

    st.delete(APP, _verstr(0))
    _equal(leader.refresh().snapshot(), follower.refresh().snapshot())
    assert _verstr(0) not in follower.snapshot().run_states


def test_unchanged_store_keeps_the_snapshot(st, db):
    _make(st, 0, random.Random(0))
    ExperimentIndex(st, APP, cache_path=db).refresh()
    follower = ExperimentIndex.follower(SqliteStore(db), APP)
    snap = follower.refresh().snapshot()
    assert follower.refresh().snapshot() is snap


def test_past_the_horizon_falls_back_to_a_full_load(st, db, monkeypatch):
    rng = random.Random(2)
    leader = ExperimentIndex(st, APP, cache_path=db)
    follower = ExperimentIndex.follower(SqliteStore(db), APP)
    for i in range(3):
        _make(st, i, rng)
    leader.refresh()
    follower.refresh()
    clock = [1e9]
    monkeypatch.setattr(index_store, "_now", lambda: clock[0])
    st.delete(APP, _verstr(0))
    leader.refresh()
    clock[0] += index_store.TOMBSTONE_TTL_SEC + 1
    _make(st, 5, rng)
    leader.refresh()  # trims the tombstone: the follower is past the horizon
    _equal(leader.snapshot(), follower.refresh().snapshot())
