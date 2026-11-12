"""Characterization: names tests patch on ``vmn_exp.sdk.run`` keep reaching
the code that uses them.

Tests (test_sdk_detach.py, test_exp_push_metrics.py, test_sdk_finalize_bounds.py,
test_sdk_run_error.py) ``setattr`` these names on the run module. Moving the
code that calls them into another module would make those patches silently
stop applying; these tests fail first.
"""
import os
from s3_helpers import meta

from vmn_exp.sdk import run as run_module
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.core.real_io import RealClock, RealHost, RealRandom
from vmn_exp.sdk.run import _real_process_hooks

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"

PATCHED_NAMES = (
    "Run",
    "start_run",
    "_finalize_open_runs",
    "_finalize_signaled",
    "install_signal_handlers",
    "final_upload_timeout_sec",
    "FINAL_REMOTE_TIMEOUT_SEC",
    "compact_by",
    "sync_to_remote",
    "error_from_exception",
)


def _run(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "s"), "runs")
    storage.save(APP, VERSTR, meta(VERSTR), {})
    run = run_module.Run(storage, APP, VERSTR, 3600, clock=RealClock(), host=RealHost(), random=RealRandom(), env=os.environ, install_hooks=_real_process_hooks())
    run._open()
    return run, storage


def test_run_module_still_exposes_its_public_and_patched_names():
    missing = [name for name in PATCHED_NAMES if not hasattr(run_module, name)]
    assert missing == []


def test_patching_compact_by_on_the_run_module_reaches_the_close_path(tmp_path, monkeypatch):
    compacted = []
    monkeypatch.setattr(run_module, "compact_by", lambda *args: compacted.append(args[:3]))
    run, storage = _run(tmp_path)
    run.finish()
    assert compacted == [(storage, APP, VERSTR)]


def test_patching_sync_to_remote_on_the_run_module_reaches_the_sync_worker(
    tmp_path, monkeypatch
):
    synced = []
    monkeypatch.setattr(run_module, "sync_to_remote", lambda *args: synced.append(args[:3]))
    run, storage = _run(tmp_path)
    run.finish()
    assert (storage, APP, VERSTR) in synced


def test_patching_error_from_exception_on_the_run_module_reaches_record_error(
    tmp_path, monkeypatch
):
    converted = []

    def convert(exc):
        converted.append(exc)
        return {"message": str(exc), "traceback": ""}

    monkeypatch.setattr(run_module, "error_from_exception", convert)
    run, _ = _run(tmp_path)
    error = ValueError("x")
    run.finish(exit_code=1, error=error)
    assert converted == [error]


def _methods(cls):
    return {name for name, value in vars(cls).items()
            if callable(value) or isinstance(value, (staticmethod, classmethod, property))}


def test_no_run_method_is_defined_by_two_bases():
    owners = {}
    for cls in (run_module.Run, *run_module.Run.__bases__):
        for name in _methods(cls):
            owners.setdefault(name, []).append(cls.__name__)
    shared = {name: classes for name, classes in owners.items() if len(classes) > 1}
    assert shared == {}
