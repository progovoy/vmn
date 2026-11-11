"""A run resumed on a fresh direct-to-bucket pod publishes its first state.

The new pod's log buffer holds nothing of the run yet: its first state write
(this attempt's id, running again) must still reach the remote, not wait for
the first log flush to give the buffer a record.
"""
import logging
import tempfile

import pytest

from vmn_exp.core.status import load_run_state
from vmn_exp.sdk import start_run
from vmn_exp.sdk.state_publisher import RunStatePublisher
from vmn_exp.storage import buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.files import METADATA_FILE
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"
CODE = "2.0.251-dev.852cb2d.0000000"


class RemoteDir(LocalSnapshotStorage):
    """A tmp_path store that reports itself remote, as a bucket does."""

    def is_remote(self):
        return True


@pytest.fixture(autouse=True)
def _git_free(tmp_path, monkeypatch):
    for var in ("VMN_WRITER_ID", "VMN_EXP_OFFLINE", "VMN_EXPERIMENT_DIR",
                "VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID",
                "VMN_RESUME_REOPEN"):
        monkeypatch.delenv(var, raising=False)
    meta = tmp_path / "vmn_metadata.yml"
    meta.write_text(
        f"verstr: {CODE}\napp_name: {APP}\n"
        "base_version: 2.0.251\nbase_commit: 852cb2d\nbranch: master\n"
    )
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(meta))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # buffers go with the test
    yield
    buffered.close_all()


def _pod(remote):
    return BufferedRemoteStorage(remote, remote.root + "-buffers", area="runs")


def _released_run(remote):
    run = start_run(APP, storage=_pod(remote), system_metrics=False,
                    heartbeat_interval_sec=3600, capture_output=False)
    run.release(reason="preempted")
    return run.id, load_run_state(remote, APP, run.id)["attempt"]


def test_a_run_resumed_on_a_fresh_buffer_publishes_its_first_state(tmp_path):
    remote = RemoteDir(str(tmp_path / "store"), "runs")
    verstr, first_attempt = _released_run(remote)

    resumed = start_run(APP, run_id=verstr, storage=_pod(remote), system_metrics=False,
                        heartbeat_interval_sec=3600, capture_output=False)
    try:
        assert resumed._state_publisher.close(timeout=10)  # the queued upload landed
        state = load_run_state(remote, APP, verstr)
        assert state["state"] == "running"
        assert state["attempt"] == resumed._state["attempt"] != first_attempt
        assert state["resume_count"] == 1
    finally:
        resumed.finish()


def _publisher_on_a_fresh_pod(tmp_path, record=True):
    remote = RemoteDir(str(tmp_path / "store"), "runs")
    if record:
        remote.save(APP, "v", {"verstr": "v", "timestamp": "2026-01-01T00:00:00Z"}, {})
    pod = _pod(remote)
    return remote, pod, RunStatePublisher(pod, APP, "v", resumes={"state": "released"})


def test_publish_on_a_buffer_without_the_record_fetches_its_metadata_first(tmp_path):
    remote, pod, publisher = _publisher_on_a_fresh_pod(tmp_path)

    publisher.publish({"state": "running", "attempt": "b"})

    assert publisher.close(timeout=10)
    assert load_run_state(remote, APP, "v")["attempt"] == "b"
    buffer = LocalSnapshotStorage(pod._buffer_root, "runs")
    assert buffer.load_file(APP, "v", METADATA_FILE)  # metadata only, never the body
    assert load_run_state(buffer, APP, "v")["attempt"] == "b"


def test_a_publish_dropped_for_a_missing_record_says_so(tmp_path, caplog):
    remote, _, publisher = _publisher_on_a_fresh_pod(tmp_path, record=False)

    with caplog.at_level(logging.DEBUG, logger="vmn_exp.sdk.state_publisher"):
        publisher.publish({"state": "running", "attempt": "b"})

    assert publisher.close(timeout=10)
    assert load_run_state(remote, APP, "v") is None
    assert "no record of v" in caplog.text
