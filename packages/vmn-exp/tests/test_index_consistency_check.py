"""Plan 11 §4.6: a journaled index re-lists a slice of its records each tick
(file signatures only), so every one is covered once per ``reconcile_sec``;
what it finds changed without a journal entry is re-read and counted as
drift. Full listings happen only at the first load and on ``reconcile``."""
import pytest

from vmn_exp.core import index as experiment_index
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
FINISHED = "state: finished\nexit_code: 0\n"
RECONCILE_SEC = 100


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
def listings(st, monkeypatch):
    calls = []
    real = st.list_files

    def list_files(app_name, keys=None):
        calls.append(None if keys is None else set(keys))
        return real(app_name, keys=keys)

    monkeypatch.setattr(st, "list_files", list_files)
    return calls


def _make(st, i):
    verstr = f"0.0.1-dev.abc.r{i}"
    st.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
    st.save_file(APP, verstr, "run_state.yml", FINISHED)
    return verstr


def _metric(st, verstr, value):
    st.append_log_entry(APP, verstr, "w", {"timestamp": "t", "type": "metrics",
                                            "values": {"acc": value}})


def _journaled(st):
    index = ExperimentIndex(st, APP, full_sweep_sec=RECONCILE_SEC)
    index.journaled = True
    return index.refresh()


def _tick(index, clock, times=1, step=1.0):
    for _ in range(times):
        clock.now += step
        index.refresh()


def _row(index, verstr):
    return {r["verstr"]: r for r in index.rows()}[verstr]


def test_every_finished_record_is_relisted_once_per_reconcile_sec(st, listings, clock):
    runs = {_make(st, i) for i in range(20)}
    index = _journaled(st)
    listings.clear()
    _tick(index, clock, times=RECONCILE_SEC + 5)
    assert None not in listings
    assert set().union(*listings) >= runs
    assert max(len(keys) for keys in listings) <= 3


def test_an_unjournaled_edit_is_reread_and_counted_as_drift(st, clock):
    runs = [_make(st, i) for i in range(10)]
    index = _journaled(st)
    _metric(st, runs[4], 0.75)
    assert index.drift == 0
    _tick(index, clock, times=RECONCILE_SEC + 5)
    assert _row(index, runs[4])["metrics"]["acc"] == 0.75
    assert index.drift == 1


def test_a_hinted_change_is_not_drift(st, clock):
    runs = [_make(st, i) for i in range(10)]
    index = _journaled(st)
    _metric(st, runs[4], 0.5)
    index.hint(runs[4])
    _tick(index, clock, times=RECONCILE_SEC + 5)
    assert _row(index, runs[4])["metrics"]["acc"] == 0.5
    assert index.drift == 0


def test_an_unhinted_new_run_is_found_within_a_reconcile_cycle(st, clock):
    _make(st, 1)
    index = _journaled(st)
    new = _make(st, 2)
    _tick(index, clock, times=2 * RECONCILE_SEC)
    assert new in {r["verstr"] for r in index.rows()}
    assert index.drift == 1


def test_no_periodic_full_listing_once_journaled(st, listings, clock):
    _make(st, 1)
    index = _journaled(st)
    listings.clear()
    _tick(index, clock, times=30, step=RECONCILE_SEC / 2)
    assert None not in listings


def test_last_reconcile_is_set_by_the_first_load_and_each_cycle(st, clock, monkeypatch):
    wall = [5000.0]
    monkeypatch.setattr("vmn_exp.core.index_sweep._wall", lambda: wall[0])
    _make(st, 1)
    index = _journaled(st)
    assert index.last_reconcile_at == 5000.0
    wall[0] = 6000.0
    _tick(index, clock, times=2 * RECONCILE_SEC)
    assert index.last_reconcile_at == 6000.0
