"""`vmn-exp run`'s run-state writes: the local copy inline, the remote copy on
a worker, newest wins; the final one retried until it lands (plan 40 C15)."""
import threading
from unittest.mock import MagicMock

import pytest
import yaml
from s3_helpers import meta
from supervisor_fakes import APP, V, WAIT_SEC, FakeRemote, FakeWait, local_first, remote_state

from vmn_exp.cli import supervisor
from vmn_exp.cli.supervisor import supervision_guard
from vmn_exp.cli.supervisor_state import StateUploads
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage

RUNNING = {"state": "running", "heartbeat_seq": 1}
FINISHED = {"state": "finished", "exit_code": 0}


@pytest.fixture
def logger(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(supervisor, "VMN_LOGGER", fake)
    return fake


def _uploads(storage, wait=None, guard=None):
    return StateUploads(storage, APP, V, wait or FakeWait(), guard or supervision_guard())


def _state(data):
    return yaml.safe_load(data) if data else None


def test_publish_returns_while_the_remote_put_hangs(tmp_path):
    hold = threading.Event()
    remote = FakeRemote(str(tmp_path / "remote"), hold=hold)
    uploads = _uploads(local_first(tmp_path, remote))

    uploads.publish(RUNNING)

    assert remote.saving.wait(WAIT_SEC)
    assert remote.state_saves == []  # still hung on the worker
    hold.set()
    assert uploads.close(WAIT_SEC)
    assert _state(remote_state(remote)) == RUNNING


def test_the_local_state_is_written_before_publish_returns(tmp_path):
    hold = threading.Event()
    remote = FakeRemote(str(tmp_path / "remote"), hold=hold)
    storage = local_first(tmp_path, remote)
    uploads = _uploads(storage)

    uploads.publish(RUNNING)

    assert _state(storage._local.load_file(APP, V, RUN_STATE_FILE)) == RUNNING
    hold.set()
    uploads.close(WAIT_SEC)


def test_a_final_state_upload_that_fails_once_lands_on_retry(tmp_path):
    remote = FakeRemote(str(tmp_path / "remote"), failures=1)
    wait = FakeWait()
    uploads = _uploads(local_first(tmp_path, remote), wait)

    uploads.publish(FINISHED, final=True)

    assert uploads.close(WAIT_SEC) is True
    assert wait.delays == [0.5]
    assert _state(remote_state(remote)) == FINISHED


def test_close_is_false_and_keeps_the_error_when_the_final_state_never_landed(tmp_path):
    remote = FakeRemote(str(tmp_path / "remote"), failures=100)
    uploads = _uploads(local_first(tmp_path, remote), FakeWait(abandon_at=2))

    uploads.publish(FINISHED, final=True)

    assert uploads.close(WAIT_SEC) is False
    assert str(uploads.last_error) == "bucket down"
    assert len(remote.state_saves) == 2


def test_an_older_beat_never_overwrites_the_final_state(tmp_path):
    hold = threading.Event()
    remote = FakeRemote(str(tmp_path / "remote"), hold=hold)
    uploads = _uploads(local_first(tmp_path, remote))

    uploads.publish(RUNNING)
    assert remote.saving.wait(WAIT_SEC)
    uploads.publish(FINISHED, final=True)
    hold.set()

    assert uploads.close(WAIT_SEC) is True
    assert _state(remote_state(remote)) == FINISHED


def test_a_failing_heartbeat_upload_warns_once_and_is_not_retried(tmp_path, logger):
    remote = FakeRemote(str(tmp_path / "remote"), failures=100)
    wait = FakeWait()
    uploads = _uploads(local_first(tmp_path, remote), wait)

    for seq in (1, 2):
        remote.saving.clear()
        uploads.publish(dict(RUNNING, heartbeat_seq=seq))
        assert remote.saving.wait(WAIT_SEC)
    assert uploads.close(WAIT_SEC) is True

    assert wait.delays == []
    assert len(remote.state_saves) == 2
    assert len(logger.warning.call_args_list) == 1


def test_a_store_without_a_remote_writes_inline_only(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "local"), "runs")
    storage.save(APP, V, meta(V), {})
    uploads = _uploads(storage)

    uploads.publish(FINISHED, final=True)

    assert _state(storage.load_file(APP, V, RUN_STATE_FILE)) == FINISHED
    assert uploads.close(0) is True


def test_a_record_the_remote_does_not_hold_is_not_uploaded(tmp_path):
    remote = FakeRemote(str(tmp_path / "remote"))
    storage = local_first(tmp_path, remote, on_remote=False)
    uploads = _uploads(storage)

    uploads.publish(FINISHED, final=True)

    assert uploads.close(WAIT_SEC) is True
    assert remote.state_saves == []
    assert _state(storage._local.load_file(APP, V, RUN_STATE_FILE)) == FINISHED


class _FailingLocal(LocalSnapshotStorage):
    def save_file(self, app_name, verstr, filename, data):
        if filename == RUN_STATE_FILE:
            raise OSError("disk full")
        return super().save_file(app_name, verstr, filename, data)


def test_a_failed_local_write_queues_nothing_for_the_remote(tmp_path):
    remote = FakeRemote(str(tmp_path / "remote"))
    storage = CachedSnapshotStorage(_FailingLocal(str(tmp_path / "local"), "runs"), remote)
    storage.save(APP, V, meta(V), {})
    uploads = _uploads(storage)

    with pytest.raises(OSError):
        uploads.publish(FINISHED, final=True)

    assert uploads.close(WAIT_SEC) is True
    assert remote.state_saves == []


class _CheckedStorage(CachedSnapshotStorage):
    def __init__(self, local, remote):
        super().__init__(local, remote)
        self.checked = []

    def ensure_local_record(self, app_name, verstr):
        self.checked.append((app_name, verstr))
        return super().ensure_local_record(app_name, verstr)


def test_the_local_record_check_goes_through_the_public_storage_method(tmp_path):
    local = LocalSnapshotStorage(str(tmp_path / "local"), "runs")
    local.save(APP, V, meta(V), {})
    storage = _CheckedStorage(local, FakeRemote(str(tmp_path / "remote")))
    uploads = _uploads(storage)

    uploads.publish(RUNNING)

    assert uploads.close(WAIT_SEC) is True
    assert storage.checked == [(APP, V)]
    assert _state(local.load_file(APP, V, RUN_STATE_FILE)) == RUNNING
