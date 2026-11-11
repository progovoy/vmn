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
import tempfile
import threading
import time

import pytest
from deferred_ship_fakes import WAIT_SEC, FakeBucket
from exp_helpers import _SRC_PATH, _PY

from vmn_exp.core.metric_block import read_headers
from vmn_exp.core.real_io import RealClock, RealHost, RealRandom
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage import buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.sdk import log_buffer
from vmn_exp.sdk.run import Run, _real_process_hooks

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"


class _CountingStorage(CachedSnapshotStorage):
    """A real local store that counts how log lines reach it."""

    def __init__(self, root):
        super().__init__(LocalSnapshotStorage(root, area="runs"))
        self.batches = []
        self.blocks = []  # points per metric-stream block (plan 12 §4.1)
        self.single_appends = 0

    def append_metric_block(self, app_name, verstr, writer_id, data):
        self.blocks.append(sum(e["n"] for h in read_headers(data) for e in h["keys"]))
        return super().append_metric_block(app_name, verstr, writer_id, data)

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
    run = Run(storage, APP, VERSTR, heartbeat, clock=RealClock(), host=RealHost(), random=RealRandom(), install_hooks=_real_process_hooks())
    run._open()
    return run


def _logged_steps(storage):
    log = LocalSnapshotStorage(storage._local.root, "runs")
    entries = log.load_merged_log(APP, VERSTR)
    return [e["step"] for e in entries if e.get("type") == "metrics"]


def test_many_metrics_reach_storage_in_a_few_batches(storage):
    run = _open_run(storage)
    for step in range(5000):
        run.log_metric("loss", 1.0 / (step + 1), step=step)
    run.finish()

    assert storage.single_appends == 0
    assert sum(storage.batches) == 1  # the final `run` entry; metrics are blocks
    assert sum(storage.blocks) == 5000
    assert len(storage.blocks) <= 5000 // log_buffer.MAX_PENDING_ENTRIES + 2
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
from vmn_exp.core.metric_block import read_headers
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.sdk import log_buffer
from vmn_exp.sdk.run import Run, _real_process_hooks
from vmn_exp.core.real_io import RealClock, RealHost, RealRandom
log_buffer.FLUSH_INTERVAL_SEC = 3600
st = CachedSnapshotStorage(LocalSnapshotStorage(sys.argv[1], area="runs"))
run = Run(st, "app", "0.0.1-dev.aaaaaaa.bbbbbbb", 3600, clock=RealClock(), host=RealHost(), random=RealRandom(),
          install_hooks=_real_process_hooks())
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
    env = dict(os.environ, PYTHONPATH=_SRC_PATH)
    proc = subprocess.Popen(
        [_PY, "-c", _SCRIPT, storage._local.root, marker, mode],
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


class _AlwaysFailingStorage(CachedSnapshotStorage):
    """A store whose log writes always fail, like a disk that stays full."""

    def __init__(self, root):
        super().__init__(LocalSnapshotStorage(root, area="runs"))
        self.attempts = 0

    def append_log_entries(self, app_name, verstr, writer_id, entries):
        self.attempts += 1
        raise OSError("disk full")


def test_log_metric_never_raises_when_the_store_keeps_failing(tmp_path):
    storage = _AlwaysFailingStorage(str(tmp_path))
    storage.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    run = _open_run(storage, heartbeat=3600)

    # Past MAX_PENDING_ENTRIES, append() used to flush synchronously on this
    # (the caller's) thread and let the store's failure raise into it.
    for step in range(log_buffer.MAX_PENDING_ENTRIES + 50):
        run.log_metric("loss", 1.0, step=step)

    run.finish()  # must not raise either
    assert storage.attempts > 0


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs fork")
def test_a_forked_child_writes_nothing_to_the_inherited_run(storage, monkeypatch):
    # Plan 30 G5: the child is not the run's writer; only the parent ships.
    monkeypatch.setattr(log_buffer, "FLUSH_INTERVAL_SEC", 3600)
    run = _open_run(storage)
    pid = os.fork()
    if pid == 0:
        try:
            run.log_metric("child", 1.0, step=42)
        finally:
            os._exit(0)
    os.waitpid(pid, 0)

    try:
        assert _logged_steps(storage) == []
    finally:
        run.finish()


def test_the_log_flusher_thread_is_not_named_like_the_run_heartbeat():
    # Code (and tests) that look for a run's liveness thread by name must not
    # mistake a log buffer's periodic flusher for one.
    import threading

    buf = log_buffer.LogBuffer(lambda batch: None)
    buf.append({"type": "metrics", "step": 0})
    try:
        names = {t.name for t in threading.enumerate()}
        assert "vmn-log-flush" in names
        assert "vmn-heartbeat" not in names
    finally:
        buf.close()


class _LogFailsOnceStorage(_CountingStorage):
    """The metric block lands, then the log append that follows raises once."""

    def __init__(self, root):
        super().__init__(root)
        self.log_failures = 1

    def append_log_entries(self, app_name, verstr, writer_id, entries):
        if self.log_failures:
            self.log_failures -= 1
            raise OSError("disk full")
        return super().append_log_entries(app_name, verstr, writer_id, entries)


def test_a_log_append_failure_does_not_duplicate_the_metric_block(tmp_path, monkeypatch):
    monkeypatch.setattr(log_buffer, "FLUSH_INTERVAL_SEC", 3600)
    storage = _LogFailsOnceStorage(str(tmp_path))
    storage.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    run = _open_run(storage, heartbeat=3600)
    run.log_metric("loss", 0.5, step=3)
    run.log_note("checkpoint")

    with pytest.raises(OSError):
        run._log_buffer.flush()
    run.finish()

    assert storage.blocks == [1]
    assert _logged_steps(storage) == [3]


def test_logging_to_a_deleted_run_warns_once(storage, monkeypatch, caplog):
    monkeypatch.setattr(log_buffer, "FLUSH_INTERVAL_SEC", 3600)
    run = _open_run(storage, heartbeat=3600)
    storage.delete(APP, VERSTR)

    with caplog.at_level("WARNING", logger="vmn_exp.sdk.run"):
        run.log_metric("loss", 0.5, step=1)
        run.log_note("lost")
        run._log_buffer.flush()
        run.log_metric("loss", 0.4, step=2)
        run._log_buffer.flush()

    warnings = [r.getMessage() for r in caplog.records if "no longer exists" in r.getMessage()]
    assert warnings == [f"vmn: run {run.id} no longer exists in the store; "
                        "1 entries were not recorded"]
    run._log_buffer.discard()


@pytest.fixture
def hung_bucket(tmp_path, monkeypatch):
    """A direct-to-bucket store whose segment creates hang until released."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    hold = threading.Event()
    bucket = FakeBucket(str(tmp_path / "bucket"), hold=hold)
    bucket.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    yield BufferedRemoteStorage(bucket, str(tmp_path), area="runs", clock=RealClock()), hold
    hold.set()
    buffered.close_all()


def test_log_metric_does_not_block_on_a_hung_bucket(hung_bucket):
    storage, hold = hung_bucket
    run = _open_run(storage, heartbeat=3600)
    done = threading.Event()

    def log_and_beat():
        for step in range(1500):
            run.log_metric("loss", 0.5, step=step)
        run._beat()
        done.set()

    threading.Thread(target=log_and_beat, daemon=True).start()
    try:
        assert done.wait(WAIT_SEC)
        assert storage._remote.creating.wait(WAIT_SEC)  # the worker is the one hung
    finally:
        hold.set()
        run.finish()


def test_a_finished_run_no_longer_receives_ship_requests(hung_bucket):
    storage, hold = hung_bucket
    hold.set()
    run = _open_run(storage, heartbeat=3600)
    run.log_metric("loss", 0.5, step=1)
    run.finish()
    shipped = storage._remote.creates

    storage.append_log_entry(APP, VERSTR, "late", {"type": "note", "text": "late"})

    assert storage._remote.creates == shipped + 1  # inline: no closed worker asked
