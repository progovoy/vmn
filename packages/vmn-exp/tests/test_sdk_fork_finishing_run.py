"""A fork while a run is finishing waits for its last uploads (plan 30 G8).

``_close_attempt`` releases the run's gate and takes it out of the open-run
registry before ``_close_remote_writers`` waits for the final log sync and
state uploads. A fork in that window must still wait for the call in flight
(within ``FORK_PAUSE_TIMEOUT_SEC``), as for an open run. Each scenario runs in
its own interpreter, so forking never touches pytest's.
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

FINISHING = threading.Event()
IN_FLIGHT = threading.Event()
RELEASE = threading.Event()
DONE = threading.Event()


class SlowSync(CachedSnapshotStorage):
    def sync_log_to_remote(self, *args):
        if FINISHING.is_set() and threading.current_thread().name == "vmn-exp-sync":
            IN_FLIGHT.set()
            RELEASE.wait()
            DONE.set()
        return super().sync_log_to_remote(*args)


storage = SlowSync(LocalSnapshotStorage(sys.argv[1], area="runs"))
storage.save("app", "0.0.1-dev.a.b", {"verstr": "0.0.1-dev.a.b"}, {})
run = Run(storage, "app", "0.0.1-dev.a.b", 60, sync_interval_sec=0)
run._open()
run.log_note("logged")


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




def finish_in_background():
    FINISHING.set()
    finisher = threading.Thread(target=run.finish, daemon=True)
    finisher.start()
    assert IN_FLIGHT.wait(10), "the final log sync never started"
    assert run._finished and run not in context.open_runs()
    return finisher
"""

_LEFT_THE_REGISTRY = r"""
finisher = finish_in_background()
deadline = time.monotonic() + 10
while run in context._OPEN_RUNS and time.monotonic() < deadline:
    time.sleep(0.01)
assert run not in context._OPEN_RUNS, "finish() never left the registry"
"""

# finish() waits for the alerts after queueing the final sync, so the run is
# finished yet still registered while that sync is in flight.
_STILL_REGISTERED = r"""
ALERTS = threading.Event()
run._finish_alerts = lambda timeout: ALERTS.wait(timeout)
finisher = finish_in_background()
assert run in context._OPEN_RUNS
threading.Timer(0.7, ALERTS.set).start()
"""

_FORK_WAITS = r"""
threading.Timer(0.5, RELEASE.set).start()
began = time.monotonic()
pid = os.fork()
if pid == 0:
    code = 0 if DONE.is_set() else 3      # the final sync had finished before the fork
    if getattr(context, "_CLOSING", None):
        code = 4                          # the child has no finishing runs of its own
    os._exit(code)
waited = time.monotonic() - began
code = wait_child(pid, 10)
assert code == 0, f"child exit {code} after {waited:.2f}s"
finisher.join(10)
assert not finisher.is_alive()
assert run not in getattr(context, "_CLOSING", ()), "the finished run stayed closing"
print("OK")
"""

_FINISHING_WAIT_IS_BOUNDED = _PRELUDE + _LEFT_THE_REGISTRY + r"""
fork_safety.FORK_PAUSE_TIMEOUT_SEC = 0.3
began = time.monotonic()
pid = os.fork()
if pid == 0:
    os._exit(0)
waited = time.monotonic() - began
assert wait_child(pid, 10) == 0
assert 0.25 <= waited < 3, f"fork waited {waited:.2f}s"
RELEASE.set()
finisher.join(10)
assert not finisher.is_alive()
print("OK")
"""


def _run_script(script, tmp_path):
    env = dict(os.environ, PYTHONPATH=_SRC_PATH)
    return subprocess.run(
        [_PY, "-c", script, str(tmp_path)],
        env=env, capture_output=True, text=True, timeout=60,
    )


@pytest.mark.parametrize("window", [_LEFT_THE_REGISTRY, _STILL_REGISTERED],
                         ids=["closing", "still-registered"])
def test_fork_waits_for_a_finishing_runs_final_upload(tmp_path, window):
    proc = _run_script(_PRELUDE + window + _FORK_WAITS, tmp_path)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr


def test_the_finishing_run_wait_is_bounded(tmp_path):
    proc = _run_script(_FINISHING_WAIT_IS_BOUNDED, tmp_path)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr
