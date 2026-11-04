"""A fork waits for ``nvmlInit`` and for an alert send in flight (plan 30, G6).

The sysmetrics init thread builds its collector (``nvmlInit``: NVML/driver state
a fork must not catch half-built) and the ``vmn-alert`` thread posts to a sink;
both now run through a gate the fork handlers pause, within the shared
``FORK_PAUSE_TIMEOUT_SEC`` budget. The priming sleep after ``nvmlInit`` is not
gated, so a fork during startup never waits for it. Each scenario runs in its
own interpreter, so forking never touches pytest's.
"""
import os
import subprocess
import sys
import threading

import pytest
from exp_helpers import _PY, _SRC_PATH

from vmn_exp.core.alerts import Alerter, make_alert
from vmn_exp.core.alerts.config import AlertConfig
from vmn_exp.sdk.background_gate import BackgroundGate

needs_fork = pytest.mark.skipif(
    not hasattr(os, "register_at_fork") or sys.platform == "win32", reason="needs fork"
)

_PRELUDE = r"""
import os, sys, threading, time
from vmn_exp.sdk import fork_safety, sysmetrics

IN_FLIGHT = threading.Event()
RELEASE = threading.Event()
DONE = threading.Event()


def wait_child(pid, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            return os.WEXITSTATUS(status)
        time.sleep(0.05)
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    sys.exit(75)


def fork_and_check():
    threading.Timer(0.5, RELEASE.set).start()
    began = time.monotonic()
    pid = os.fork()
    if pid == 0:
        os._exit(0 if DONE.is_set() else 3)   # the slow call had finished
    waited = time.monotonic() - began
    code = wait_child(pid, 10)
    assert code == 0, f"child exit {code}: the fork did not wait"
    return waited
"""

_FORK_DURING_NVML_INIT = _PRELUDE + r"""
sysmetrics.MIN_SAMPLE_INTERVAL_SEC = 5.0   # the priming sleep: never waited for


def slow_build_collector(pid=None):
    IN_FLIGHT.set()
    RELEASE.wait()
    DONE.set()
    return lambda: {}


sysmetrics.build_collector = slow_build_collector
sampler = sysmetrics.Sampler(lambda values: None, enabled=True)
assert IN_FLIGHT.wait(10), "nvmlInit never started"
waited = fork_and_check()
assert waited < 3, f"the fork waited {waited:.2f}s: it waited for the priming sleep"
print("OK")
"""

_FORK_DURING_ALERT_SEND = _PRELUDE + r"""
from vmn_exp.core.alerts import Alerter
from vmn_exp.core.alerts.config import AlertConfig
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage


class SlowSink:
    def send(self, alert, timeout):
        IN_FLIGHT.set()
        RELEASE.wait()
        DONE.set()


storage = LocalSnapshotStorage(sys.argv[1], area="runs")
storage.save("app", "0.0.1-dev.a.b", {"verstr": "0.0.1-dev.a.b"}, {})
run = Run(storage, "app", "0.0.1-dev.a.b", 60)
run._open()
run._alerter_instance = Alerter(AlertConfig(sinks=[SlowSink()], on=["alert"]))
assert run.alert("loss exploded") is True
assert IN_FLIGHT.wait(10), "the alert send never started"
fork_and_check()
run.finish()
print("OK")
"""


def _run_script(script, tmp_path):
    env = dict(os.environ, PYTHONPATH=_SRC_PATH)
    return subprocess.run(
        [_PY, "-c", script, str(tmp_path)],
        env=env, capture_output=True, text=True, timeout=60,
    )


@needs_fork
def test_fork_waits_for_nvml_init_but_not_the_priming_sleep(tmp_path):
    proc = _run_script(_FORK_DURING_NVML_INIT, tmp_path)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr


@needs_fork
def test_fork_waits_for_an_alert_send_in_flight(tmp_path):
    proc = _run_script(_FORK_DURING_ALERT_SEND, tmp_path)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr


class _RecordingSink:
    def __init__(self):
        self.sent = threading.Event()

    def send(self, alert, timeout):
        self.sent.set()


def _alert():
    return make_alert("alert", "app", "0.0.1-dev.a.b", "title")


def test_send_async_waits_while_its_gate_is_paused():
    sink, gate = _RecordingSink(), BackgroundGate()
    alerter = Alerter(AlertConfig(sinks=[sink], on=["alert"]))
    gate.pause()
    alerter.send_async(_alert(), gate=gate)
    assert not sink.sent.wait(0.3)
    gate.resume()
    assert sink.sent.wait(5)


def test_send_async_without_a_gate_sends_at_once():
    sink = _RecordingSink()
    Alerter(AlertConfig(sinks=[sink], on=["alert"])).send_async(_alert())
    assert sink.sent.wait(5)
