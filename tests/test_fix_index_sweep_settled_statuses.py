"""Only ``running`` records may still change on their own; every other status
(``created``, ``stuck``, ``succeeded``, ``failed``) should settle to the same
reduced re-listing rate once its directory signature stops moving, instead of
being re-listed on every fast-tier refresh forever.

See :mod:`version_stamp.core.experiment_index_sweep`'s ``_may_change``.
"""
import datetime
import os
import time

import pytest

from version_stamp.cli.snapshot import LocalSnapshotStorage
from version_stamp.core import experiment_index
from version_stamp.core.experiment_index import ExperimentIndex
from version_stamp.core.experiment_index_sweep import Sweep

APP = "app"
FULL_SWEEP_SEC = 300


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _ago_iso(seconds):
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds)
    return dt.isoformat().replace("+00:00", "Z")


# -- direct: Sweep._may_change at "steady state" (sig already recorded once,
#    same as it is at the start of the second refresh in a real index) -------


CREATED_RS = None
RUNNING_RS = {"state": "running", "heartbeat": _ago_iso(5), "heartbeat_interval_sec": 30}
STUCK_RS = {"state": "running", "heartbeat": _ago_iso(1000), "heartbeat_interval_sec": 30}
SUCCEEDED_RS = {"state": "finished", "exit_code": 0}
FAILED_RS = {"state": "finished", "exit_code": 1}

SETTLED_STATUSES = (CREATED_RS, STUCK_RS, SUCCEEDED_RS, FAILED_RS)


def _steady_state(run_state, sig=("s", 1), touched=None):
    sweep = Sweep(None, APP, full_sweep_sec=FULL_SWEEP_SEC)
    sweep._sigs = {"v": sig}
    if touched is not None:
        sweep._touched["v"] = touched
    records = {"v": {"meta": {"verstr": "v"}, "run_state": run_state, "rs_sig": None}}
    return sweep, records


def test_running_may_change_even_with_an_unchanged_sig():
    sweep, records = _steady_state(RUNNING_RS)
    assert sweep._may_change(records, "v", ("s", 1), 1000) is True


@pytest.mark.parametrize("run_state", SETTLED_STATUSES)
def test_a_settled_status_stops_being_relisted_once_its_sig_holds(run_state):
    sweep, records = _steady_state(run_state)
    assert sweep._may_change(records, "v", ("s", 1), 1000) is False


@pytest.mark.parametrize("run_state", SETTLED_STATUSES)
def test_a_settled_status_still_relists_when_its_sig_moves(run_state):
    sweep, records = _steady_state(run_state)
    assert sweep._may_change(records, "v", ("s", 2), 1000) is True


@pytest.mark.parametrize("run_state", SETTLED_STATUSES)
def test_a_settled_status_stays_listed_within_the_touched_window(run_state):
    sweep, records = _steady_state(run_state, touched=990)
    assert sweep._may_change(records, "v", ("s", 1), 1000) is True


# -- through the index, with real storage ------------------------------------


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
    return LocalSnapshotStorage(str(tmp_path), subdir="experiments")


@pytest.fixture
def listed(st, monkeypatch):
    calls = []
    real = st.list_files

    def spy(app_name, keys=None):
        calls.append(None if keys is None else set(keys))
        return real(app_name, keys=keys)

    monkeypatch.setattr(st, "list_files", spy)
    return calls


def _make(st, i, run_state=None):
    verstr = f"0.0.1-dev.abc.r{i}"
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}
    st.save(APP, verstr, meta, {})
    if run_state is not None:
        st.save_file(APP, verstr, "run_state.yml", run_state)
    return verstr


def _backdate_run_state(st, verstr, seconds_ago):
    """A genuinely ``stuck`` run's run_state.yml was itself last written long
    ago, not just the heartbeat value it holds — derive_status only calls a
    run stuck once both the writer clock (the heartbeat) and the store clock
    (this mtime) agree it is stale."""
    path = os.path.join(st._snapshot_dir(APP, verstr), "run_state.yml")
    old = time.time() - seconds_ago
    os.utime(path, (old, old))


def test_created_and_stuck_records_settle_like_finished_ones(st, listed, clock):
    created = _make(st, 1)
    stuck = _make(st, 2, "state: running\nheartbeat: '2000-01-01T00:00:00Z'\n")
    _backdate_run_state(st, stuck, seconds_ago=10_000)
    live = _make(st, 3, f"state: running\nheartbeat: '{_now_iso()}'\n")
    index = ExperimentIndex(st, APP, full_sweep_sec=FULL_SWEEP_SEC)
    index.refresh()
    assert listed == [None]  # the first refresh is always a full sweep

    clock.now += 1
    index.refresh()
    assert listed[1:] == [{live}]
    # Nothing was lost: all three are still in the index.
    assert set(index.run_states()) == {created, stuck, live}
