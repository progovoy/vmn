"""A direct-to-bucket buffer holds the only local copy of a run's final state
(plan 40 C13): it is not removed until the remote holds a final state."""
import logging
import os
import tempfile

import pytest
import yaml
from deferred_ship_fakes import FakeBucket
from s3_helpers import entry, meta

from vmn_exp.core.status import RUN_STATE_FILE, load_run_state
from vmn_exp.storage import buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.cached import local_side
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.core.real_io import RealClock

APP, V, W = "app", "v", "w"
RUNNING = {"state": "running", "attempt": "a1"}
FINISHED = {"state": "finished", "attempt": "a1", "exit_code": 0}


@pytest.fixture(autouse=True)
def _temp(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "buffers"))
    (tmp_path / "buffers").mkdir()
    yield
    buffered.close_all()


@pytest.fixture
def bucket(tmp_path):
    remote = FakeBucket(str(tmp_path / "bucket"))
    remote.save(APP, V, meta(V), {})
    return remote


@pytest.fixture
def pod(bucket, tmp_path):
    return BufferedRemoteStorage(bucket, str(tmp_path / "buffers"), area="runs", clock=RealClock())


def _store_state(side, state):
    side.save_file(APP, V, RUN_STATE_FILE, yaml.dump(state))


def _finish_in_buffer(pod, bucket, remote_state):
    """A run whose remote state is *remote_state* and whose final state is in
    the buffer alone, as the SDK's inline state write leaves it."""
    _store_state(bucket, remote_state)
    pod.append_log_entry(APP, V, W, entry(0))  # the first ships at once
    _store_state(local_side(pod), FINISHED)
    return pod._buffer_root


def _refuse_state_writes(*args, **kwargs):
    raise ConnectionError("the store is out of reach")


def test_a_finished_runs_log_sync_keeps_the_buffer_while_the_remote_state_is_running(pod, bucket):
    root = _finish_in_buffer(pod, bucket, RUNNING)

    pod.sync_log_to_remote(APP, V, W)

    assert load_run_state(local_side(pod), APP, V) == FINISHED
    assert os.path.isdir(root)


def test_a_finished_runs_log_sync_removes_the_buffer_once_the_remote_state_is_final(pod, bucket):
    root = _finish_in_buffer(pod, bucket, RUNNING)
    _store_state(bucket, FINISHED)

    pod.sync_log_to_remote(APP, V, W)

    assert not os.path.exists(root)


def test_close_publishes_a_final_state_the_remote_never_received(pod, bucket):
    root = _finish_in_buffer(pod, bucket, RUNNING)

    pod.close()

    assert load_run_state(bucket, APP, V) == FINISHED
    assert not os.path.exists(root)


def test_close_keeps_the_buffer_when_the_final_state_cannot_be_published(
    monkeypatch, pod, bucket, caplog
):
    root = _finish_in_buffer(pod, bucket, RUNNING)
    monkeypatch.setattr(bucket, "save_file_if_match", _refuse_state_writes)

    with caplog.at_level(logging.WARNING):
        pod.close()

    assert load_run_state(bucket, APP, V) == RUNNING
    assert load_run_state(LocalSnapshotStorage(root, "runs"), APP, V) == FINISHED
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(root in w and V in w for w in warnings)


def test_close_removes_the_buffer_when_another_attempt_finished_the_run(pod, bucket):
    other = {"state": "finished", "attempt": "b2", "exit_code": 1}
    root = _finish_in_buffer(pod, bucket, other)

    pod.close()

    assert load_run_state(bucket, APP, V) == other
    assert not os.path.exists(root)


def test_a_buffer_with_no_finished_run_closes_as_before(pod, bucket):
    _store_state(bucket, RUNNING)
    pod.append_log_entry(APP, V, W, entry(0))
    _store_state(local_side(pod), RUNNING)
    root = pod._buffer_root

    pod.close()

    assert load_run_state(bucket, APP, V) == RUNNING
    assert not os.path.exists(root)
