"""System-metrics imports never run on the background init thread.

An import in flight on another thread at ``fork()`` leaves that module's import
lock held in the child, which then deadlocks on its own first import of the
module (seen: ``start_run()`` then ``os.fork()`` — a DataLoader's workers — hung
in ``env._cuda_info`` importing ``pynvml`` while ``vmn-sysmetrics-init`` was
still scanning for the missing module). So the optional imports happen on the
thread that builds the Sampler; only the slow collector setup is off-thread.
"""
import sys
import threading
import time

from vmn_exp.sdk import sysmetrics


def _wait_built(sampler, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if sampler._collector is not None or not sampler._enabled:
            return
        time.sleep(0.01)
    raise AssertionError("collector never built")


def test_optional_imports_run_on_the_calling_thread(monkeypatch):
    importers = []

    def recording_import(name, package=None):
        importers.append((name, threading.current_thread().name))
        raise ImportError(name)

    for name in ("psutil", "pynvml"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sysmetrics, "_MISSING", set(), raising=False)
    monkeypatch.setattr(sysmetrics.importlib, "import_module", recording_import)
    sampler = sysmetrics.Sampler(lambda values: None, enabled=True)
    _wait_built(sampler)

    caller = threading.current_thread().name
    assert {name for name, _ in importers} == {"psutil", "pynvml"}
    assert all(thread == caller for _, thread in importers), importers
