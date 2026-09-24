"""SDK log writes are batched: one append per flush, never one per metric.

``run.log_metric`` used to stat the record, open the log, write one line and
close it on every call (~2k calls/s). Entries now buffer in memory and reach
storage as whole lines in batches — at most every ~1s, on each heartbeat, when
the buffer fills, and on ``finish()``/SIGTERM/interpreter exit — so a training
loop can log tens of thousands of points a second and none is lost.
"""
import os
import signal
import subprocess
import sys
import time

import pytest
from helpers import _PROJECT_ROOT, _PY

from version_stamp.cli.snapshot import CachedSnapshotStorage, LocalSnapshotStorage
from version_stamp.exp import log_buffer
from version_stamp.exp.run import Run

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"


class _CountingStorage(CachedSnapshotStorage):
    """A real local store that counts how log lines reach it."""

    def __init__(self, root):
        super().__init__(LocalSnapshotStorage(root, subdir="experiments"))
        self.batches = []
        self.single_appends = 0

    def append_log_entries(self, app_name, verstr, writer_id, entries):
        self.batches.append(len(entries))
        return super().append_log_entries(app_name, verstr, writer_id, entries)

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        self.single_appends += 1
        return super().append_log_entry(app_name, verstr, writer_id, entry)


@pytest.fixture
def storage(tmp_path):
    st = _CountingStorage(str(tmp_path))
    st.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


def _open_run(storage, heartbeat=60):
    run = Run(storage, APP, VERSTR, heartbeat)
    run._open()
    return run


def _logged_steps(storage):
    log = LocalSnapshotStorage(storage._local.vmn_root_path, "experiments")
    entries = log.load_merged_log(APP, VERSTR)
    return [e["step"] for e in entries if e.get("type") == "metrics"]


def test_many_metrics_reach_storage_in_a_few_batches(storage):
    run = _open_run(storage)
    for step in range(5000):
        run.log_metric("loss", 1.0 / (step + 1), step=step)
    run.finish()

    assert storage.single_appends == 0
    assert sum(storage.batches) == 5001  # the metrics and the final `run` entry
    assert len(storage.batches) <= 1 + 5000 // log_buffer.MAX_PENDING_ENTRIES + 2
    assert _logged_steps(storage) == list(range(5000))


def test_a_full_buffer_is_written_before_finish(storage):
    run = _open_run(storage)
    for step in range(log_buffer.MAX_PENDING_ENTRIES):
        run.log_metric("loss", 0.5, step=step)

    assert len(_logged_steps(storage)) == log_buffer.MAX_PENDING_ENTRIES
    run.finish()


def test_a_quiet_run_is_flushed_within_about_a_second(storage):
    run = _open_run(storage)
    run.log_metric("loss", 0.5, step=1)
    deadline = time.monotonic() + 10
    while not _logged_steps(storage) and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        assert _logged_steps(storage) == [1]
    finally:
        run.finish()


def test_each_heartbeat_flushes_the_buffer(storage, monkeypatch):
    monkeypatch.setattr(log_buffer, "FLUSH_INTERVAL_SEC", 3600)
    run = _open_run(storage)
    run.log_metric("loss", 0.5, step=7)
    assert _logged_steps(storage) == []

    run._beat()

    assert _logged_steps(storage) == [7]
    run.finish()


def test_entries_logged_before_finish_are_durable_after_it(storage, monkeypatch):
    monkeypatch.setattr(log_buffer, "FLUSH_INTERVAL_SEC", 3600)
    run = _open_run(storage)
    for step in range(10):
        run.log_metric("loss", 0.5, step=step)
    run.finish()

    assert _logged_steps(storage) == list(range(10))


def test_a_finished_run_still_accepts_writes(storage):
    run = _open_run(storage)
    run.finish()
    run.log_metric("late", 1.0, step=99)

    assert _logged_steps(storage) == [99]


_SCRIPT = """
import os, sys, time
from version_stamp.cli.snapshot import CachedSnapshotStorage, LocalSnapshotStorage
from version_stamp.exp import log_buffer
from version_stamp.exp.run import Run
log_buffer.FLUSH_INTERVAL_SEC = 3600
st = CachedSnapshotStorage(LocalSnapshotStorage(sys.argv[1], subdir="experiments"))
run = Run(st, "app", "0.0.1-dev.aaaaaaa.bbbbbbb", 3600)
run._open()
for step in range(25):
    run.log_metric("loss", 0.5, step=step)
open(sys.argv[2], "w").close()
if sys.argv[3] == "exit":
    sys.exit(0)
time.sleep(120)
"""


def _spawn(storage, tmp_path, mode):
    marker = str(tmp_path / "marker")
    env = dict(os.environ, PYTHONPATH=_PROJECT_ROOT)
    proc = subprocess.Popen(
        [_PY, "-c", _SCRIPT, storage._local.vmn_root_path, marker, mode],
        env=env,
    )
    deadline = time.monotonic() + 60
    while not os.path.exists(marker) and proc.poll() is None:
        assert time.monotonic() < deadline, "child never logged"
        time.sleep(0.05)
    return proc


def test_buffered_entries_survive_interpreter_exit(storage, tmp_path):
    proc = _spawn(storage, tmp_path, "exit")
    assert proc.wait(timeout=60) == 0

    assert _logged_steps(storage) == list(range(25))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_buffered_entries_survive_sigterm(storage, tmp_path):
    proc = _spawn(storage, tmp_path, "wait")
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=60) == -signal.SIGTERM

    assert _logged_steps(storage) == list(range(25))


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs fork")
def test_a_forked_child_writes_straight_through(storage, monkeypatch):
    monkeypatch.setattr(log_buffer, "FLUSH_INTERVAL_SEC", 3600)
    run = _open_run(storage)
    pid = os.fork()
    if pid == 0:
        try:
            run.log_metric("child", 1.0, step=42)
        finally:
            os._exit(0)
    os.waitpid(pid, 0)

    assert _logged_steps(storage) == [42]
    run.finish()
