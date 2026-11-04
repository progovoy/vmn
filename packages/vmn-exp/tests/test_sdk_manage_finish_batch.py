"""``manage.finish_runs``: an orchestrator closes many runs in one call.

Each ref gets its own result — the verstr finished, or the error that
refused it — and one bad run never stops the others.
"""
import os
import time

import pytest
import yaml

from vmn_exp.core.status import RUN_STATE_FILE, load_run_state
from vmn_exp.sdk import manage
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

APP = "app"
STUCK = ["0.0.1-dev.aaaaaaa.1111111", "0.0.1-dev.aaaaaaa.2222222"]
LIVE = "0.0.1-dev.aaaaaaa.3333333"
DONE = "0.0.1-dev.aaaaaaa.4444444"
MISSING = "0.0.1-dev.nope"


def _beat(age_sec):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_sec))


@pytest.fixture
def storage(tmp_path):
    st = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "runs"))
    states = {v: {"state": "running", "heartbeat": "2026-01-01T00:00:00Z"} for v in STUCK}
    states[LIVE] = {"state": "running", "heartbeat": _beat(0)}
    states[DONE] = {"state": "finished", "exit_code": 0}
    for verstr, state in states.items():
        st.save(APP, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})
        state.update(attempt="pod", heartbeat_interval_sec=30)
        st.save_file(APP, verstr, RUN_STATE_FILE, yaml.dump(state))
        if verstr in STUCK:
            _backdate(st, verstr)
    return st


def _backdate(storage, verstr, age_sec=3600):
    """Stale by the store's clock too, so the run reads stuck, not live."""
    path = os.path.join(storage._local._snapshot_dir(APP, verstr), RUN_STATE_FILE)
    then = time.time() - age_sec
    os.utime(path, (then, then))


def _exit_code(storage, verstr):
    return load_run_state(storage, APP, verstr).get("exit_code")


def test_finish_runs_finishes_every_run(storage):
    result = manage.finish_runs(APP, STUCK, 137, error="OOMKilled", storage=storage)

    assert result == {v: v for v in STUCK}
    assert [_exit_code(storage, v) for v in STUCK] == [137, 137]
    assert load_run_state(storage, APP, STUCK[0])["error"]["message"] == "OOMKilled"


def test_finish_runs_reports_each_failure_per_ref(storage):
    refs = [STUCK[0], LIVE, DONE, MISSING]

    result = manage.finish_runs(APP, refs, 1, storage=storage)

    assert list(result) == refs
    assert result[STUCK[0]] == STUCK[0]
    assert isinstance(result[LIVE], manage.FinishRefusedError)
    assert result[LIVE].reason == "live"
    assert isinstance(result[DONE], manage.FinishRefusedError)
    assert result[DONE].reason == "finished"
    assert isinstance(result[MISSING], ValueError)
    assert not isinstance(result[MISSING], manage.FinishRefusedError)
    assert _exit_code(storage, LIVE) is None
    assert _exit_code(storage, DONE) == 0


def test_finish_runs_keys_by_the_ref_given(storage):
    ref = STUCK[0][:-4]

    assert manage.finish_runs(APP, [ref], 0, storage=storage) == {ref: STUCK[0]}
    assert _exit_code(storage, STUCK[0]) == 0


def test_finish_runs_force_live_spares_finished_runs(storage):
    result = manage.finish_runs(APP, [LIVE, DONE], 143, force="live", storage=storage)

    assert result[LIVE] == LIVE
    assert result[DONE].reason == "finished"
    assert (_exit_code(storage, LIVE), _exit_code(storage, DONE)) == (143, 0)


def test_finish_runs_rejects_a_bad_exit_code_up_front(storage):
    with pytest.raises(ValueError, match="exit_code"):
        manage.finish_runs(APP, STUCK, "boom", storage=storage)
    assert _exit_code(storage, STUCK[0]) is None


def test_finish_runs_rejects_a_bad_force_up_front(storage):
    with pytest.raises(ValueError, match="force"):
        manage.finish_runs(APP, STUCK, 0, force="yes", storage=storage)
    assert _exit_code(storage, STUCK[0]) is None


def test_finish_runs_of_no_refs_is_empty(storage):
    assert manage.finish_runs(APP, [], 0, storage=storage) == {}
