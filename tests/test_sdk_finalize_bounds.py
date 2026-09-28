"""Finalizing open runs (on SIGTERM and at exit) stays within one bounded wait.

A signaled process has a grace period to die within, so the SIGTERM handler
waits at most ``FINAL_REMOTE_TIMEOUT_SEC`` for the finalization. With several
open runs and a hung remote store, each run waiting that long for its own
uploads would spend the whole budget on the first run: the others would never
write their final state and would later derive as ``stuck``.
"""
import signal
import threading
import time

import pytest
from helpers import _bootstrap

from vmn_exp.core.status import load_run_state
from vmn_exp.sdk import run as run_module
from vmn_exp.sdk import signals, start_run
from vmn_exp.snapshot import CachedSnapshotStorage, LocalSnapshotStorage

TIMEOUT = 0.5
RUNS = 3


class _HungRemote:
    """A remote store whose every write hangs while it is down."""

    def __init__(self, inner):
        self._inner = inner
        self.up = threading.Event()
        self.up.set()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def save_file(self, *args, **kwargs):
        self.up.wait(timeout=60)
        return self._inner.save_file(*args, **kwargs)


@pytest.fixture
def hung_runs(app_layout, tmp_path, monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(run_module, "FINAL_REMOTE_TIMEOUT_SEC", TIMEOUT)
    _bootstrap(app_layout)
    local = LocalSnapshotStorage(app_layout.repo_path, subdir="experiments")
    remote = _HungRemote(LocalSnapshotStorage(str(tmp_path), subdir="remote"))
    storage = CachedSnapshotStorage(local, remote)
    runs = [
        start_run(
            app_layout.app_name, storage=storage, heartbeat_interval_sec=60, nested=True
        )
        for _ in range(RUNS)
    ]
    remote.up.clear()
    try:
        yield local, runs
    finally:
        remote.up.set()
        for run in runs:
            run.finish()


def _exit_codes(local, runs):
    return [load_run_state(local, run.app_name, run.id)["exit_code"] for run in runs]


def test_sigterm_writes_every_open_runs_final_state_within_its_budget(hung_runs):
    local, runs = hung_runs

    signals._run_bounded(run_module._finalize_signaled, signal.SIGTERM, TIMEOUT)

    assert _exit_codes(local, runs) == [128 + signal.SIGTERM] * RUNS


def test_finalizing_several_runs_waits_for_their_uploads_once(hung_runs):
    local, runs = hung_runs

    started = time.monotonic()
    run_module._finalize_open_runs()
    elapsed = time.monotonic() - started

    assert _exit_codes(local, runs) == [0] * RUNS
    assert elapsed < 2 * TIMEOUT, f"waited {elapsed:.2f}s: one timeout per run"
