"""A fork while a run's background thread is mid storage call never deadlocks the child.

The SDK registers ``os.register_at_fork`` handlers: before a fork every open
run's background threads are paused (waiting, within a bound, for a call in
flight), after it the parent resumes them and the child gets fresh SDK locks.
The storage here stands in for boto3: its log write holds a module lock (a
connection pool's) while it waits, and the forked child then takes that lock.
Each scenario runs in its own interpreter, so forking never touches pytest's.
"""
import os
import subprocess
import sys

import pytest
from exp_helpers import _PY, _SRC_PATH

pytestmark = pytest.mark.skipif(
    not hasattr(os, "register_at_fork") or sys.platform == "win32", reason="needs fork"
)

_PRELUDE = r"""
import os, sys, threading, time
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.sdk import context, fork_safety
from vmn_exp.sdk.run import Run

POOL_LOCK = threading.Lock()   # boto3's connection-pool lock, say
IN_FLIGHT = threading.Event()
RELEASE = threading.Event()
DONE = threading.Event()


class SlowStorage(CachedSnapshotStorage):
    blocking = True

    def append_log_entries(self, *args):
        if not SlowStorage.blocking or threading.current_thread().name != "vmn-log-flush":
            return super().append_log_entries(*args)
        SlowStorage.blocking = False
        with POOL_LOCK:
            IN_FLIGHT.set()
            RELEASE.wait()
            result = super().append_log_entries(*args)
        DONE.set()
        return result


storage = SlowStorage(LocalSnapshotStorage(sys.argv[1], area="runs"))
storage.save("app", "0.0.1-dev.a.b", {"verstr": "0.0.1-dev.a.b"}, {})
run = Run(storage, "app", "0.0.1-dev.a.b", 60)
run._open()
run.log_note("flushed by the background flusher")
assert IN_FLIGHT.wait(10), "the flusher never started its write"


def wait_child(pid, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            return os.WEXITSTATUS(status)
        time.sleep(0.05)
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    print("HUNG: the forked child deadlocked")
    sys.exit(75)
"""

_FORK_WAITS_FOR_THE_CALL = _PRELUDE + r"""
threading.Timer(0.5, RELEASE.set).start()
pid = os.fork()
if pid == 0:
    code = 0 if DONE.is_set() else 3      # the write had finished before the fork
    with POOL_LOCK:                       # deadlocks if the fork caught it held
        pass
    if context.current_run() is not None:
        code = 4
    if run.pause_background(timeout=1) is not True:   # fresh gate, no parent threads
        code = 5
    with context._LOCK:                   # the SDK's own lock is usable
        pass
    os._exit(code)
code = wait_child(pid, 10)
assert code == 0, f"child exit {code}"
before = len([e for e in storage._local.load_merged_log("app", "0.0.1-dev.a.b")])
run.log_note("after the fork")   # the parent's flusher was resumed
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    if len(storage._local.load_merged_log("app", "0.0.1-dev.a.b")) > before:
        break
    time.sleep(0.05)
else:
    sys.exit(6)
run.finish()
print("OK")
"""

_FORK_WAIT_IS_BOUNDED = _PRELUDE + r"""
fork_safety.FORK_PAUSE_TIMEOUT_SEC = 0.3
began = time.monotonic()
pid = os.fork()
if pid == 0:
    os._exit(0)
waited = time.monotonic() - began
assert wait_child(pid, 10) == 0
assert 0.25 <= waited < 3, f"fork waited {waited:.2f}s"
RELEASE.set()
run.finish()
print("OK")
"""


def _run_script(script, tmp_path):
    env = dict(os.environ, PYTHONPATH=_SRC_PATH)
    proc = subprocess.run(
        [_PY, "-c", script, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc


def test_fork_waits_for_the_call_in_flight_and_the_child_does_not_hang(tmp_path):
    proc = _run_script(_FORK_WAITS_FOR_THE_CALL, tmp_path)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr


def test_fork_waits_at_most_the_bound_for_a_stuck_call(tmp_path):
    proc = _run_script(_FORK_WAIT_IS_BOUNDED, tmp_path)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr
