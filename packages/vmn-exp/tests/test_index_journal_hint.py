"""Plan 11 §5.2 / phase 2c: a journaled index lists only what the journal
names (``hint``) plus its live records; full listings happen at the first
load and on ``reconcile`` (or every ``full_sweep_sec``), never per tick."""
import pytest

from vmn_exp.core import index as experiment_index
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
FINISHED = "state: finished\nexit_code: 0\n"
RECONCILE_SEC = 3600


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
def st(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), area="runs")


@pytest.fixture
def spy(st, monkeypatch):
    """Every storage listing/read the index makes."""
    calls = {"list_files": [], "names": 0, "load_file": []}
    real_list, real_names, real_load = st.list_files, st.list_record_names, st.load_file

    def list_files(app_name, keys=None):
        calls["list_files"].append(None if keys is None else set(keys))
        return real_list(app_name, keys=keys)

    def names(app_name):
        calls["names"] += 1
        return real_names(app_name)

    def load_file(app_name, verstr, *a, **kw):
        calls["load_file"].append(verstr)
        return real_load(app_name, verstr, *a, **kw)

    monkeypatch.setattr(st, "list_files", list_files)
    monkeypatch.setattr(st, "list_record_names", names)
    monkeypatch.setattr(st, "load_file", load_file)
    return calls


def _make(st, i, run_state=FINISHED):
    verstr = f"0.0.1-dev.abc.r{i}"
    stamp = f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z"
    st.save(APP, verstr, {"verstr": verstr, "timestamp": stamp}, {})
    st.append_log_entry(APP, verstr, "w", {"timestamp": "t", "type": "metrics",
                                            "values": {"loss": float(i)}})
    if run_state is not None:
        st.save_file(APP, verstr, "run_state.yml", run_state)
    return verstr


def _journaled(st):
    index = ExperimentIndex(st, APP, full_sweep_sec=RECONCILE_SEC)
    index.journaled = True
    return index


def _reset(spy):
    spy["list_files"].clear()
    spy["load_file"].clear()
    spy["names"] = 0


def _verstrs(index):
    return {r["verstr"] for r in index.rows()}


def test_the_first_refresh_is_a_full_listing(st, spy, clock):
    run = _make(st, 1)
    index = _journaled(st).refresh()
    assert None in spy["list_files"]
    assert _verstrs(index) == {run}


def test_a_tick_without_hints_lists_no_names_and_no_finished_records(st, spy, clock):
    for i in range(5):
        _make(st, i)
    index = _journaled(st).refresh()
    _reset(spy)
    clock.now += 1
    index.refresh()
    assert spy["names"] == 0
    assert None not in spy["list_files"]
    assert all(not keys for keys in spy["list_files"])


def test_per_tick_listing_does_not_grow_with_finished_runs(st, spy, clock):
    index = _journaled(st).refresh()

    def per_tick_cost(first, count):
        for i in range(first, first + count):
            index.hint(_make(st, i))
        clock.now += 1
        index.refresh()  # the hinted runs load
        _reset(spy)
        clock.now += 1
        index.refresh()
        return sum(len(keys or ()) for keys in spy["list_files"]), spy["names"]

    assert per_tick_cost(0, 3) == per_tick_cost(10, 30) == (0, 0)
    assert len(index.rows()) == 33


def test_hint_rereads_only_that_record(st, spy, clock):
    runs = [_make(st, i) for i in range(4)]
    index = _journaled(st).refresh()
    st.append_log_entry(APP, runs[2], "w", {"timestamp": "t", "type": "metrics",
                                             "values": {"acc": 0.5}})
    _reset(spy)
    clock.now += 1
    index.hint(runs[2])
    index.refresh()
    assert [keys for keys in spy["list_files"] if keys] == [{runs[2]}]
    assert set(spy["load_file"]) <= {runs[2]}
    row = {r["verstr"]: r for r in index.rows()}[runs[2]]
    assert row["metrics"]["acc"] == 0.5


def test_a_hint_for_an_unchanged_record_does_nothing(st, spy, clock):
    runs = [_make(st, i) for i in range(3)]
    index = _journaled(st).refresh()
    generation = index.generation
    _reset(spy)
    clock.now += 1
    index.hint(runs[1])
    index.refresh()
    assert index.generation == generation
    assert spy["load_file"] == []


def test_a_hinted_new_run_is_visible_without_a_full_listing(st, spy, clock):
    _make(st, 1)
    index = _journaled(st).refresh()
    new = _make(st, 2)
    _reset(spy)
    clock.now += 1
    index.hint(new)
    index.refresh()
    assert None not in spy["list_files"] and spy["names"] == 0
    assert new in _verstrs(index)


def test_an_unhinted_new_run_waits_for_reconcile(st, spy, clock):
    _make(st, 1)
    index = _journaled(st).refresh()
    new = _make(st, 2)
    clock.now += 1
    index.refresh()
    assert new not in _verstrs(index)
    index.reconcile()
    _reset(spy)
    index.refresh()
    assert None in spy["list_files"]
    assert new in _verstrs(index)


def test_the_reconcile_interval_forces_a_full_listing(st, spy, clock):
    _make(st, 1)
    index = _journaled(st).refresh()
    new = _make(st, 2)
    clock.now += RECONCILE_SEC
    index.refresh()
    assert new in _verstrs(index)


def test_running_records_are_still_listed_every_tick(st, spy, clock):
    live = _make(st, 1, "state: running\nheartbeat: '2026-01-01T00:00:00Z'\n")
    _make(st, 2)
    index = _journaled(st).refresh()
    _reset(spy)
    clock.now += 1
    index.refresh()
    assert {live} in spy["list_files"]
