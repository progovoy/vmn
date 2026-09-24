"""Stuck detection that survives clock skew, and heartbeats a slow remote can't stall.

* Readers measure a heartbeat's age on the *storage's* clock (the mtime of
  ``run_state.yml``) when the storage provides one, so a writer whose clock is
  behind never reads ``stuck`` while alive, and one whose clock is ahead does not
  read ``running`` long after it died.
* Every beat bumps ``heartbeat_seq``, a monotonic counter in ``run_state.yml``.
* The remote copy of the run state and the log sync are published off the
  heartbeat thread: a stalled S3 PUT cannot delay the local heartbeat.
"""
import datetime
import os
import subprocess
import threading
import time

import pytest
from helpers import _PROJECT_ROOT, _PY, _bootstrap, _storage

from version_stamp.cli.snapshot import CachedSnapshotStorage, LocalSnapshotStorage
from version_stamp.core import experiment_status as st
from version_stamp.exp import start_run

NOW = datetime.datetime(2026, 9, 21, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _running(heartbeat):
    return {
        "state": "running",
        "started_at": _iso(NOW - datetime.timedelta(hours=2)),
        "heartbeat": _iso(heartbeat),
        "heartbeat_interval_sec": 30,
        "exit_code": None,
    }


def _ago(seconds):
    return NOW - datetime.timedelta(seconds=seconds)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# the reader rule
# ---------------------------------------------------------------------------


def test_writer_clock_behind_is_running_when_the_store_saw_a_fresh_write():
    state = _running(heartbeat=_ago(600))  # the writer's clock is 10 min slow

    assert st.derive_status(state, now=NOW) == st.STUCK
    assert st.derive_status(state, now=NOW, observed_at=_ago(5)) == st.RUNNING


def test_writer_clock_ahead_is_stuck_once_the_store_saw_no_write():
    state = _running(heartbeat=NOW + datetime.timedelta(hours=1))

    assert st.derive_status(state, now=NOW) == st.RUNNING
    assert st.derive_status(state, now=NOW, observed_at=_ago(600)) == st.STUCK


def test_observed_at_never_overrides_a_terminal_exit_code():
    state = dict(_running(heartbeat=_ago(5)), exit_code=0, state="finished")

    assert st.derive_status(state, now=NOW, observed_at=_ago(9999)) == st.SUCCEEDED


def test_status_fields_measure_staleness_on_the_store_clock():
    state = _running(heartbeat=_ago(600))

    fields = st.status_fields(state, now=NOW, observed_at=_ago(5))

    assert fields["status"] == st.RUNNING
    assert fields["stale_sec"] == 5.0


def test_observed_at_is_read_from_a_local_store(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    storage.save("app", "v1", {"verstr": "v1"}, {})
    storage.save_file("app", "v1", st.RUN_STATE_FILE, "state: running\n")

    observed = st.run_state_observed_at(storage, "app", "v1")

    age = (datetime.datetime.now(datetime.timezone.utc) - observed).total_seconds()
    assert -5 < age < 60
    assert st.run_state_observed_at(storage, "app", "missing") is None


class _SecondsStore:
    """An S3-shaped store: mtimes in float seconds."""

    def record_files(self, app_name, verstr):
        return {st.RUN_STATE_FILE: (10, NOW.timestamp(), "etag")}


class _NoSignatures:
    pass


def test_observed_at_handles_second_resolution_and_absent_support():
    assert st.run_state_observed_at(_SecondsStore(), "app", "v") == NOW
    assert st.run_state_observed_at(_NoSignatures(), "app", "v") is None


# ---------------------------------------------------------------------------
# the writer
# ---------------------------------------------------------------------------


def _wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _seq(storage, app_name, verstr):
    state = st.load_run_state(storage, app_name, verstr) or {}
    return state.get("heartbeat_seq")


def test_sdk_heartbeat_seq_increases_every_beat(app_layout):
    _bootstrap(app_layout)
    storage = _storage(app_layout)

    with start_run(app_layout.app_name, heartbeat_interval_sec=0.05) as run:
        assert _seq(storage, app_layout.app_name, run.id) == 0
        assert _wait_for(lambda: _seq(storage, app_layout.app_name, run.id) >= 3)


class _StallingRemote:
    """A remote whose run-state PUT hangs until released."""

    def __init__(self, inner):
        self._inner = inner
        self.release = threading.Event()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def save_file(self, app_name, verstr, filename, data):
        if filename == st.RUN_STATE_FILE:
            self.release.wait(timeout=60)
        return self._inner.save_file(app_name, verstr, filename, data)


def test_a_stalled_remote_put_does_not_delay_local_heartbeats(app_layout, tmp_path):
    _bootstrap(app_layout)
    local = LocalSnapshotStorage(app_layout.repo_path, subdir="experiments")
    remote = _StallingRemote(LocalSnapshotStorage(str(tmp_path), subdir="remote"))
    storage = CachedSnapshotStorage(local, remote)

    run = start_run(app_layout.app_name, storage=storage, heartbeat_interval_sec=0.05)
    try:
        assert _wait_for(lambda: _seq(local, app_layout.app_name, run.id) >= 3), (
            "the local heartbeat waited for the stalled remote PUT"
        )
    finally:
        remote.release.set()
        run.finish()

    final = st.load_run_state(remote._inner, app_layout.app_name, run.id)
    assert final["exit_code"] == 0, "the remote kept a stale, non-final state"


class _StallingSync:
    def __init__(self, inner):
        self._inner = inner
        self.release = threading.Event()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def sync_log_to_remote(self, *args):
        self.release.wait(timeout=60)


def test_a_stalled_log_sync_does_not_delay_heartbeats(app_layout):
    _bootstrap(app_layout)
    storage = _StallingSync(_storage(app_layout))

    run = start_run(
        app_layout.app_name,
        storage=storage,
        heartbeat_interval_sec=0.05,
        sync_interval_sec=0.05,
    )
    try:
        assert _wait_for(lambda: _seq(storage, app_layout.app_name, run.id) >= 5)
    finally:
        storage.release.set()
        run.finish()


def test_cli_exp_run_publishes_heartbeat_seq(app_layout):
    _bootstrap(app_layout)
    env = dict(
        os.environ,
        VMN_WORKING_DIR=app_layout.repo_path,
        PYTHONPATH=os.pathsep.join(
            p for p in (_PROJECT_ROOT, os.environ.get("PYTHONPATH")) if p
        ),
    )
    proc = subprocess.run(
        [
            _PY, "-m", "version_stamp.cli.entry", "exp", "run",
            app_layout.app_name, "--heartbeat-interval", "1", "--",
            _PY, "-c", "import time; time.sleep(3.5)",
        ],
        cwd=app_layout.repo_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    storage = _storage(app_layout)
    (meta,) = storage.list_snapshots(app_layout.app_name)
    assert _seq(storage, app_layout.app_name, meta["verstr"]) >= 2
