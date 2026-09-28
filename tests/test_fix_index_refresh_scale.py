"""Scale guard: at N records with M of them changing, a refresh costs O(M),
not O(N). At 100k runs with ~500 live writers the index publishes a
generation every second; per-record work on all N — judging every record's
status to decide what to list, re-deriving every row's run-state time for the
snapshot, re-sorting every key, re-comparing every record on a full sweep —
cost >1s of CPU per refresh and starved the server. Counts calls instead of
timing, so it cannot flake."""
import datetime
import json
import os

import pytest
import yaml

from vmn_exp.core import index as experiment_index
from vmn_exp.core import index_record, index_snapshot, index_sweep
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
N = 2000
M = 20
FULL_SWEEP_SEC = 300


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _now_iso():
    return _iso(datetime.datetime.now(datetime.timezone.utc))


class Store:
    def __init__(self, root):
        self.st = LocalSnapshotStorage(root, subdir="experiments")
        self.base = os.path.join(root, ".vmn", APP, "experiments")

    def add(self, i, run_state):
        verstr = f"0.0.1-dev.abc1234.def5678.r{i}"
        folder = os.path.join(self.base, verstr)
        os.makedirs(folder)
        stamp = _iso(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
                     + datetime.timedelta(seconds=i))
        with open(os.path.join(folder, "metadata.yml"), "w") as f:
            yaml.dump({"verstr": verstr, "timestamp": stamp, "name": f"run-{i}"}, f)
        self.log(verstr, 0)
        with open(os.path.join(folder, "run_state.yml"), "w") as f:
            f.write(run_state)
        return verstr

    def log(self, verstr, value):
        with open(os.path.join(self.base, verstr, "log.w.jsonl"), "a") as f:
            f.write(json.dumps({"timestamp": _now_iso(), "type": "metrics",
                                "values": {"loss": value}}) + "\n")

    def beat(self, verstr, seq):
        self.st.save_file(APP, verstr, "run_state.yml",
                          f"state: running\nheartbeat: '{_now_iso()}'\nheartbeat_seq: {seq}\n")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(experiment_index, "_monotonic", c)
    return c


@pytest.fixture
def live_store(tmp_path):
    store = Store(str(tmp_path))
    for i in range(N):
        store.add(i, "state: finished\nexit_code: 0\n")
    store.live = [store.add(N + i, f"state: running\nheartbeat: '{_now_iso()}'\n")
                  for i in range(M)]
    return store


def _counter(monkeypatch, module, name):
    calls = []
    real = getattr(module, name)

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, counted)
    return calls


def _churn(store, cycle):
    for verstr in store.live:
        store.beat(verstr, cycle)
        store.log(verstr, cycle)


def test_a_fast_refresh_does_per_record_work_only_for_what_changed(
    live_store, clock, tmp_path, monkeypatch
):
    index = ExperimentIndex(live_store.st, APP, cache_path=str(tmp_path / "idx.sqlite"),
                            full_sweep_sec=FULL_SWEEP_SEC)
    index.refresh()
    clock.now += 1
    index.refresh()

    settled = _counter(monkeypatch, index_sweep, "_settled")
    observed = _counter(monkeypatch, index_snapshot, "_observed_at")
    stamps = _counter(monkeypatch, experiment_index, "_timestamp")
    for cycle in range(1, 4):
        _churn(live_store, cycle)
        new = live_store.add(N + M + cycle, f"state: running\nheartbeat: '{_now_iso()}'\n")
        live_store.live.append(new)
        clock.now += 1
        index.refresh()
        snap = index.snapshot()
        assert snap.row(new) is not None
        assert snap.rows[-1]["verstr"] == new
        assert all(snap.row(v)["metrics"]["loss"] == cycle for v in live_store.live[:M])

    changed = 3 * (M + 3)
    assert len(settled) <= 3 * changed
    assert len(observed) <= 3 * changed
    assert len(stamps) <= 3 * changed * 20  # a bisection per new record, not a full sort


def test_a_full_sweep_refreshes_only_the_records_whose_files_changed(
    live_store, clock, tmp_path, monkeypatch
):
    index = ExperimentIndex(live_store.st, APP, cache_path=str(tmp_path / "idx.sqlite"),
                            full_sweep_sec=FULL_SWEEP_SEC)
    index.refresh()
    _churn(live_store, 1)
    compared = _counter(monkeypatch, index_record, "log_signatures")
    clock.now += FULL_SWEEP_SEC + 1  # due: this refresh lists every record
    index.refresh()

    assert len(compared) <= 3 * M
    assert all(index.snapshot().row(v)["metrics"]["loss"] == 1 for v in live_store.live)
    assert len(index.snapshot().rows) == N + M


def test_the_rows_match_a_direct_read_after_churn(live_store, clock, tmp_path):
    index = ExperimentIndex(live_store.st, APP, cache_path=str(tmp_path / "idx.sqlite"),
                            full_sweep_sec=FULL_SWEEP_SEC)
    index.refresh()
    for cycle in range(1, 4):
        _churn(live_store, cycle)
        live_store.st.delete(APP, live_store.live.pop())
        live_store.add(N + M + cycle, "state: finished\nexit_code: 1\n")
        clock.now += 1 if cycle < 3 else FULL_SWEEP_SEC + 1
        index.refresh()
    rows, states = experiment_index.direct_rows(live_store.st, APP)
    snap = index.snapshot()
    assert [dict(r) for r in snap.rows] == rows
    assert snap.run_states == states
