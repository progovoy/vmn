"""Out-of-pod finish and notes (plan 28 API3): ``manage.finish_run``,
``manage.log_note``, ``manage.log_metrics``.

An orchestrator finishes a run it does not host: the final ``run_state.yml``
is written directly, with no heartbeat and no ``running`` state first. A run
another attempt is still heartbeating (by both clocks), or one that already
finished, is refused unless forced.
"""
import os
import time

import pytest
import yaml
from s3_helpers import cached_host, meta, mocked_bucket, s3_storage

from vmn_exp.core.log import experiment_row
from vmn_exp.core.status import RUN_STATE_FILE, load_run_state, status_fields
from vmn_exp.sdk import manage
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"
STARTED = "2026-01-01T00:00:00Z"


@pytest.fixture
def storage(tmp_path):
    st = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "runs"))
    st.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": STARTED}, {})
    return st


def _state(storage):
    return load_run_state(storage, APP, VERSTR)


def _status(storage):
    return status_fields(_state(storage))


def _row(storage):
    meta = storage.load_metadata(APP, VERSTR)
    return experiment_row(1, meta, storage.load_merged_log(APP, VERSTR))


def _entries(storage, kind):
    return [e for e in storage.load_merged_log(APP, VERSTR) if e.get("type") == kind]


def _write_state(storage, age_sec=0, **fields):
    """A run state written *age_sec* ago by both clocks (heartbeat + mtime)."""
    beat = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_sec))
    state = {"state": "running", "attempt": "pod1", "started_at": STARTED,
             "heartbeat": beat, "heartbeat_interval_sec": 30, "exit_code": None}
    state.update(fields)
    storage.save_file(APP, VERSTR, RUN_STATE_FILE, yaml.dump(state))
    path = os.path.join(storage._local._snapshot_dir(APP, VERSTR), RUN_STATE_FILE)
    then = time.time() - age_sec
    os.utime(path, (then, then))


def _stuck(storage):
    _write_state(storage, age_sec=3600)


def test_finish_a_stuck_run_without_reopening_it(storage):
    _stuck(storage)

    assert manage.finish_run(APP, VERSTR, 137, storage=storage) == VERSTR

    state = _state(storage)
    assert state["state"] == "finished"
    assert state["exit_code"] == 137
    assert state["started_at"] == STARTED
    assert state["finished_at"]
    assert state["duration_sec"] > 0
    assert _status(storage)["status"] == "failed"


def test_finish_writes_a_fresh_attempt(storage):
    _stuck(storage)
    manage.finish_run(APP, VERSTR, 0, storage=storage)
    assert _state(storage)["attempt"] not in (None, "pod1")


def test_finish_a_run_that_never_started(storage):
    manage.finish_run(APP, VERSTR, 1, storage=storage, end_reason="closed")

    state = _state(storage)
    assert (state["state"], state["exit_code"], state["end_reason"]) == ("finished", 1, "closed")
    assert state["duration_sec"] is None
    assert _status(storage)["status"] == "failed"


def test_finish_records_the_error(storage):
    _stuck(storage)

    manage.finish_run(APP, VERSTR, 1, error="OOMKilled after 3 retries", storage=storage)

    assert _state(storage)["error"] == {"message": "OOMKilled after 3 retries",
                                        "source": "user"}
    assert [e["message"] for e in _entries(storage, "error")] == [
        "OOMKilled after 3 retries"]
    assert _status(storage)["error_summary"] == "OOMKilled after 3 retries"


def test_finish_replaces_a_released_runs_end_reason(storage):
    _write_state(storage, age_sec=5, state="released", end_reason="released")

    manage.finish_run(APP, VERSTR, 0, storage=storage)

    assert "end_reason" not in _state(storage)
    assert _status(storage)["status"] == "succeeded"


def test_finish_refuses_a_run_heartbeating_elsewhere(storage):
    _write_state(storage, age_sec=5)

    with pytest.raises(manage.FinishRefusedError, match="force"):
        manage.finish_run(APP, VERSTR, 1, storage=storage)

    assert _state(storage)["state"] == "running"


def test_a_fresh_store_write_alone_keeps_a_run_live(storage):
    """Stale by the writer's clock, fresh by the store's: still live."""
    _write_state(storage, age_sec=0, heartbeat="2026-01-01T00:00:00Z")

    with pytest.raises(manage.FinishRefusedError):
        manage.finish_run(APP, VERSTR, 1, storage=storage)


def test_finish_refuses_a_finished_run(storage):
    _write_state(storage, age_sec=5, state="finished", exit_code=0)

    with pytest.raises(manage.FinishRefusedError, match="finished"):
        manage.finish_run(APP, VERSTR, 1, storage=storage)

    assert _state(storage)["exit_code"] == 0


def test_force_finishes_a_live_run_and_its_heartbeats_stop(storage):
    run = Run(storage, APP, VERSTR, 60)
    run._open()
    try:
        manage.finish_run(APP, VERSTR, 143, end_reason="evicted", force=True,
                          storage=storage)
        run._publish_heartbeat()

        state = _state(storage)
        assert (state["state"], state["exit_code"]) == ("finished", 143)
        assert run._state_publisher.superseded
    finally:
        run.finish()


def test_finish_rejects_a_non_integer_exit_code(storage):
    with pytest.raises(ValueError, match="exit_code"):
        manage.finish_run(APP, VERSTR, "boom", storage=storage)
    assert _state(storage) is None


def test_finish_an_unknown_run_raises(storage):
    with pytest.raises(ValueError):
        manage.finish_run(APP, "0.0.1-dev.nope", 0, storage=storage)


def test_log_note_from_outside(storage):
    assert manage.log_note(APP, VERSTR, "closed by orchestrator", storage=storage) == VERSTR
    assert [e["text"] for e in _entries(storage, "note")] == ["closed by orchestrator"]


def test_log_metrics_from_outside(storage):
    manage.log_metrics(APP, VERSTR, {"retries": 3}, storage=storage)
    manage.log_metrics(APP, VERSTR, {"loss": 0.5}, step=7, storage=storage)

    assert _row(storage)["metrics"] == {"retries": 3.0, "loss": 0.5}


def test_finish_and_note_reach_the_remote_with_no_heartbeat(tmp_path, monkeypatch):
    """A one-shot caller: nothing will sync these to the bucket later."""
    with mocked_bucket(monkeypatch):
        host = cached_host(tmp_path, "orchestrator")
        host.save(APP, VERSTR, meta(VERSTR), {})

        manage.log_note(APP, VERSTR, "closed at study end", storage=host)
        manage.finish_run(APP, VERSTR, 0, storage=host)

        remote = s3_storage()
        assert load_run_state(remote, APP, VERSTR)["state"] == "finished"
        notes = [e["text"] for e in remote.load_merged_log(APP, VERSTR)
                 if e["type"] == "note"]
        assert notes == ["closed at study end"]
