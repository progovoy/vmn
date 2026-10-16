"""Plan 25 F2: ``max_age_sec`` means what it says. ``refresh_if_stale(0)``
answers the current snapshot (only a first load refreshes); a caller that
needs freshness passes a positive age: the sweep agent's early-stop check
its check interval. One-shot readers keep refreshing."""
import pytest

from vmn_exp.cli.sweep.agent import _EarlyStopCheck
from vmn_exp.core import index as experiment_index
from vmn_exp.core.alerts import watch_app
from vmn_exp.core.index import ExperimentIndex, indexed_snapshot
from vmn_exp.sdk import reader
from vmn_exp.storage.open import open_storage

APP = "my_app"
FINISHED = "state: finished\nexit_code: 0\n"
SPEC = {
    "metric": {"name": "loss", "goal": "min"},
    "early_terminate": {"type": "median", "min_iter": 3, "min_trials": 1,
                        "check_interval_sec": 10.0},
}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch, tmp_path):
    monkeypatch.setenv("VMN_EXP_CACHE_DIR", str(tmp_path / "cache"))
    c = Clock()
    monkeypatch.setattr(experiment_index, "_monotonic", c)
    return c


@pytest.fixture
def storage(tmp_path):
    return open_storage(None, str(tmp_path / "store"), area="runs")


@pytest.fixture
def listings(storage, monkeypatch):
    """``["names" | "full" | "keys"]``, one per storage listing."""
    calls = []
    real_names, real_files = storage.list_record_names, storage.list_files

    def list_record_names(app_name):
        calls.append("names")
        return real_names(app_name)

    def list_files(app_name, keys=None, **kwargs):
        calls.append("full" if keys is None else "keys")
        return real_files(app_name, keys=keys, **kwargs)

    monkeypatch.setattr(storage, "list_record_names", list_record_names)
    monkeypatch.setattr(storage, "list_files", list_files)
    return calls


def _make(storage, verstr, parent=None, run_state=FINISHED):
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{len(verstr)}Z",
            "parent": parent}
    storage.save(APP, verstr, meta, {})
    storage.save_file(APP, verstr, "run_state.yml", run_state)
    return verstr


def test_refresh_if_stale_0_answers_the_current_snapshot(storage, listings, clock):
    _make(storage, "v1")
    index = ExperimentIndex(storage, APP)
    first = index.refresh_if_stale(0)  # a first load still loads
    _make(storage, "v2")
    clock.now += 3600
    del listings[:]
    assert index.refresh_if_stale(0) is first
    assert listings == []


def test_a_positive_age_refreshes_only_once_the_snapshot_is_older(storage, listings, clock):
    _make(storage, "v1")
    index = ExperimentIndex(storage, APP)
    index.refresh_if_stale(10)
    _make(storage, "v2")
    clock.now += 9
    assert [r["verstr"] for r in index.refresh_if_stale(10).rows] == ["v1"]
    clock.now += 1
    assert [r["verstr"] for r in index.refresh_if_stale(10).rows] == ["v1", "v2"]


def test_indexed_snapshot_without_an_age_takes_the_loaded_index_as_is(storage, clock):
    _make(storage, "v1")
    indexed_snapshot(storage, APP)
    _make(storage, "v2")
    clock.now += 3600
    assert [r["verstr"] for r in indexed_snapshot(storage, APP).rows] == ["v1"]
    assert len(indexed_snapshot(storage, APP, max_age_sec=60).rows) == 2


def test_the_early_stop_check_refreshes_at_its_check_interval(storage, listings, clock):
    _make(storage, "s", run_state="state: running\n")
    own = _make(storage, "t1", parent="s", run_state="state: running\n")
    _make(storage, "t2", parent="s")
    check = _EarlyStopCheck(SPEC, storage, APP, "s", own)
    try:
        check._check(None)
        assert listings[-1] == "full"  # the agent's first look at the app
        del listings[:]
        clock.now += 1
        check._check(None)
        assert listings == []  # younger than the check interval
        clock.now += 9
        check._check(None)
        assert "names" in listings and "full" not in listings
    finally:
        check.close()


def test_a_watch_tick_after_the_first_lists_no_store(storage, listings, clock):
    class Wants:
        def wants(self, status):
            return True

    _make(storage, "v1")
    watch_app(storage, APP, Wants(), 86400)
    del listings[:]
    clock.now += 60
    _make(storage, "v2")
    watch_app(storage, APP, Wants(), 86400)
    assert "full" not in listings
    assert listings.count("keys") == 1  # the new run's files only


def test_the_reader_refreshes_on_every_call(storage, clock):
    _make(storage, "v1")
    assert [r["verstr"] for r in reader.list_runs(APP, storage=storage)] == ["v1"]
    _make(storage, "v2")
    assert [r["verstr"] for r in reader.list_runs(APP, storage=storage)] == ["v1", "v2"]
    assert reader.get_run(APP, "v2", storage=storage)["verstr"] == "v2"
