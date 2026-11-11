"""A run's final state that fails to upload is retried and reported, never
silent; a failing heartbeat upload warns once and is not retried in place.
"""
import logging

import yaml
from final_upload_fakes import WAIT_SEC, FakeAbandon, FakeRemoteState
from s3_helpers import meta

from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.sdk import run as run_module
from vmn_exp.sdk.background_gate import BackgroundGate
from vmn_exp.sdk.run import Run
from vmn_exp.sdk.state_publisher import RunStatePublisher
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

APP = "app"
X = "0.0.1-dev.aaaaaaa.bbbbbbb"
FINAL = {"state": "finished", "attempt": "mine", "exit_code": 0}
BEAT = {"state": "running", "attempt": "mine", "heartbeat_seq": 1}


def _publisher(remote, abandon, gate=None):
    return RunStatePublisher(remote, APP, X, gate, abandon=abandon)


def _stored(remote):
    return yaml.safe_load(remote.data) if remote.data else None


def test_a_final_state_that_fails_once_is_uploaded_on_retry():
    remote, abandon = FakeRemoteState(failures=1), FakeAbandon()
    publisher = _publisher(remote, abandon)

    publisher.publish(FINAL, final=True)

    assert publisher.close(WAIT_SEC) is True
    assert _stored(remote)["state"] == "finished"
    assert abandon.delays == [0.5]


def test_close_is_false_when_the_final_state_never_landed():
    remote, abandon = FakeRemoteState(failures=100), FakeAbandon(blocking=True)
    publisher = _publisher(remote, abandon)

    publisher.publish(FINAL, final=True)
    assert abandon.waiting.wait(WAIT_SEC)

    assert publisher.close(0) is False
    assert isinstance(publisher.last_error, OSError)
    assert remote.data is None


def test_close_is_true_when_the_final_state_was_superseded():
    theirs = yaml.dump({"state": "finished", "attempt": "theirs", "exit_code": 3})
    remote, abandon = FakeRemoteState(stored=theirs), FakeAbandon()
    publisher = _publisher(remote, abandon)

    publisher.publish(FINAL, final=True)

    assert publisher.close(WAIT_SEC) is True
    assert publisher.superseded
    assert _stored(remote)["exit_code"] == 3


def test_a_failing_heartbeat_upload_warns_once_then_stays_quiet(caplog):
    remote, abandon = FakeRemoteState(failures=100), FakeAbandon()
    publisher = _publisher(remote, abandon)

    with caplog.at_level(logging.DEBUG):
        publisher.publish(BEAT, heartbeat=True)
        assert remote.attempted.wait(WAIT_SEC)
        remote.attempted.clear()
        publisher.publish(dict(BEAT, heartbeat_seq=2), heartbeat=True)
        assert remote.attempted.wait(WAIT_SEC)
        assert publisher.close(WAIT_SEC) is True

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [f"vmn: could not upload the state of run {X}: remote down"]


def test_a_heartbeat_failure_is_not_retried_in_place():
    remote, abandon = FakeRemoteState(failures=100), FakeAbandon()
    publisher = _publisher(remote, abandon)

    publisher.publish(BEAT, heartbeat=True)

    assert publisher.close(WAIT_SEC) is True
    assert remote.attempts == 1
    assert abandon.delays == []


def test_the_gate_is_free_between_final_attempts():
    remote, abandon = FakeRemoteState(failures=1), FakeAbandon(blocking=True)
    gate = BackgroundGate()
    publisher = _publisher(remote, abandon, gate)

    publisher.publish(FINAL, final=True)
    assert abandon.waiting.wait(WAIT_SEC)

    assert gate.pause(timeout=WAIT_SEC) is True
    gate.resume()
    abandon.proceed()
    assert publisher.close(WAIT_SEC) is True
    assert _stored(remote)["state"] == "finished"


class _StateRefusingRemote:
    """A remote store whose every write of a run state fails."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def save_file_if_match(self, app_name, verstr, filename, *args):
        if filename == RUN_STATE_FILE:
            raise OSError("remote down")
        return self._inner.save_file_if_match(app_name, verstr, filename, *args)


def test_finish_warns_that_the_final_state_was_not_uploaded(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC", raising=False)
    monkeypatch.setattr(run_module, "FINAL_REMOTE_TIMEOUT_SEC", 0.3)
    local = LocalSnapshotStorage(str(tmp_path / "local"), "runs")
    remote = LocalSnapshotStorage(str(tmp_path / "remote"), "runs")
    for side in (local, remote):
        side.save(APP, X, meta(X), {})
    run = Run(CachedSnapshotStorage(local, _StateRefusingRemote(remote)), APP, X, 3600)
    run._open()

    with caplog.at_level(logging.WARNING):
        run.finish()

    assert f"vmn: the final state of run {X} was not uploaded: remote down" in caplog.text
