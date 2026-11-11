"""Finalizing open runs (on SIGTERM and at exit) stays within one bounded wait.

A signaled process has a grace period to die within, so the SIGTERM handler
waits at most ``FINAL_REMOTE_TIMEOUT_SEC`` for the finalization. With several
open runs and a hung remote store, each run waiting that long for its own
uploads would spend the whole budget on the first run: the others would never
write their final state and would later derive as ``stuck``.
"""
import os
import signal
import threading
import time

import pytest
from exp_helpers import _bootstrap

from vmn_exp.core.status import load_run_state
from vmn_exp.sdk import run as run_module
from vmn_exp.sdk import signals, start_run
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.areas import local_store_root
from vmn_exp.core.real_io import RealClock, RealHost, RealRandom

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
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(run_module, "FINAL_REMOTE_TIMEOUT_SEC", TIMEOUT)
    before = set(threading.enumerate())
    _bootstrap(app_layout)
    local = LocalSnapshotStorage(local_store_root(app_layout.repo_path), area="runs")
    remote = _HungRemote(LocalSnapshotStorage(str(tmp_path), area="remote"))
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
        # The uploads the hung remote held write on into the repo: let them
        # land before app_layout removes it.
        for thread in set(threading.enumerate()) - before:
            thread.join(10)


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


# ---------------------------------------------------------------------------
# VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC
# ---------------------------------------------------------------------------

TIMEOUT_ENV = "VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC"


@pytest.mark.parametrize(
    "value, expected",
    [("5", 5.0), ("0.25", 0.25), ("0", 60), ("-1", 60), ("soon", 60), ("nan", 60), ("inf", 60)],
)
def test_the_final_upload_timeout_reads_a_positive_env_value(monkeypatch, value, expected):
    monkeypatch.setenv(TIMEOUT_ENV, value)
    assert run_module.final_upload_timeout_sec() == expected


def test_the_final_upload_timeout_defaults_to_a_minute(monkeypatch):
    monkeypatch.delenv(TIMEOUT_ENV, raising=False)
    assert run_module.final_upload_timeout_sec() == 60


def test_the_env_timeout_bounds_the_shared_upload_wait(hung_runs, monkeypatch):
    local, runs = hung_runs
    monkeypatch.setattr(run_module, "FINAL_REMOTE_TIMEOUT_SEC", 60)
    monkeypatch.setenv(TIMEOUT_ENV, str(TIMEOUT))

    started = time.monotonic()
    run_module._finalize_open_runs()
    elapsed = time.monotonic() - started

    assert _exit_codes(local, runs) == [0] * RUNS
    assert elapsed < 2 * TIMEOUT, f"waited {elapsed:.2f}s"


@pytest.fixture
def sigterm_restored():
    handler = signal.getsignal(signal.SIGTERM)
    state = dict(signals._STATE)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, handler)
        signals._STATE.update(state)


def test_the_sigterm_handler_waits_at_most_the_env_timeout(monkeypatch, sigterm_restored):
    hung = threading.Event()
    monkeypatch.setattr(run_module, "_finalize_signaled", lambda signum: hung.wait(10))
    monkeypatch.setenv(TIMEOUT_ENV, "0.2")
    chained = []
    signal.signal(signal.SIGTERM, lambda signum, frame: chained.append(signum))
    run_module.install_signal_handlers()

    started = time.monotonic()
    try:
        signal.raise_signal(signal.SIGTERM)
        elapsed = time.monotonic() - started
    finally:
        hung.set()

    assert chained == [signal.SIGTERM]
    assert elapsed < 5, f"the handler waited {elapsed:.2f}s"


def test_a_second_sigterm_during_finalization_starts_no_second_finalizer(sigterm_restored):
    calls = []

    def finalize(signum):
        calls.append(signum)
        if len(calls) == 1:
            # Arrives while the first handler still waits for this finalizer.
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.5)

    chained = []
    signal.signal(signal.SIGTERM, lambda signum, frame: chained.append(signum))
    signals.install(finalize, timeout=lambda: 5)

    signal.raise_signal(signal.SIGTERM)

    assert calls == [signal.SIGTERM]
    assert chained == [signal.SIGTERM]


# ---------------------------------------------------------------------------
# The SIGTERM budget: a pod's default grace period is 30 s
# ---------------------------------------------------------------------------


def test_the_sigterm_budget_defaults_to_25_seconds(monkeypatch, sigterm_restored):
    monkeypatch.delenv(TIMEOUT_ENV, raising=False)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)

    run_module.install_signal_handlers()

    assert run_module.sigterm_timeout_sec() == 25
    assert signals._STATE["timeout"]() == 25


@pytest.mark.parametrize("value, expected", [("40", 40.0), ("5", 5.0)])
def test_the_env_timeout_also_sets_the_sigterm_budget(monkeypatch, value, expected):
    monkeypatch.setenv(TIMEOUT_ENV, value)
    assert run_module.sigterm_timeout_sec() == expected


def test_a_lowered_module_timeout_still_bounds_the_sigterm_budget(monkeypatch):
    monkeypatch.delenv(TIMEOUT_ENV, raising=False)
    monkeypatch.setattr(run_module, "FINAL_REMOTE_TIMEOUT_SEC", TIMEOUT)
    assert run_module.sigterm_timeout_sec() == TIMEOUT


APP = "app"
X = "0.0.1-dev.abc1234.0000001"
Y = "0.0.1-dev.abc1234.0000002"


@pytest.fixture
def local_runs(tmp_path, monkeypatch):
    """Runs over a plain local store (no git, no remote); finished afterwards."""
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", TIMEOUT_ENV):
        monkeypatch.delenv(key, raising=False)
    local = LocalSnapshotStorage(str(tmp_path), area="runs")
    made = []

    def make(verstr):
        local.save(APP, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})
        made.append(Run(local, APP, verstr, 3600, clock=RealClock(), host=RealHost(), random=RealRandom()))
        return made[-1]

    try:
        yield local, make
    finally:
        for run in made:
            run.finish()


def _record_deadlines(run, calls):
    """Wrap *run*'s final writers to record the deadline each is given."""
    for name, index in (("_record_final", 1), ("_close_remote_writers", 0)):
        real = getattr(run, name)

        def recording(*args, _real=real, _name=name, _index=index, **kwargs):
            calls.append((_name, args[_index]))
            return _real(*args, **kwargs)

        setattr(run, name, recording)


def test_finish_and_atexit_keep_the_one_minute_default(local_runs):
    _, make = local_runs
    finished, abandoned = make(X), make(Y)
    calls = []
    for run in (finished, abandoned):
        _record_deadlines(run, calls)
        run._open()

    started = time.monotonic()
    finished.finish()
    run_module._finalize_open_runs()

    budgets = [deadline - started for _, deadline in calls]
    assert len(budgets) == 4
    assert all(59 < budget <= 60.5 for budget in budgets), budgets


def test_the_signal_finalizer_uses_the_deadline_it_is_given(local_runs):
    local, make = local_runs
    run = make(X)
    calls = []
    _record_deadlines(run, calls)
    run._open()
    deadline = time.monotonic() + 7

    run_module._finalize_open_runs(1, deadline=deadline)

    assert calls == [("_record_final", deadline), ("_close_remote_writers", deadline)]
    assert load_run_state(local, APP, X)["exit_code"] == 1


class _HungMediaUploads:
    """Media uploads whose close hangs until released, as on a stuck store."""

    def __init__(self):
        self.released = threading.Event()
        self.waited = None

    def close(self, timeout):
        self.waited = timeout
        self.released.wait(timeout)
        return False


def test_hung_media_uploads_do_not_keep_sigterm_from_writing_the_final_state(
    local_runs, monkeypatch
):
    local, make = local_runs
    budget = 0.4
    monkeypatch.setenv(TIMEOUT_ENV, str(budget))
    run = make(X)
    media = run._media_uploads = _HungMediaUploads()
    run._open()

    try:
        run_module._finalize_signaled(signal.SIGTERM)
    finally:
        media.released.set()

    assert media.waited <= budget / 2 + 0.01, f"media got {media.waited:.2f}s"
    assert load_run_state(local, APP, X)["exit_code"] == 128 + signal.SIGTERM
