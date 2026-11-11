"""A Run reads time and its process from the clock and host it is handed
(plan 44 G10); start_run, the SDK's entry point, hands it the real ones."""
import pytest
from fakes.clock import FakeClock
from fakes.host import FakeHost
from fakes.random import FakeRandom

from vmn_exp.core.real_io import RealClock, RealHost
from vmn_exp.sdk import guest_run  # noqa: F401  (subclasses Run on import)
from vmn_exp.sdk import run as run_module
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"


class _Submits:
    def __init__(self):
        self.calls = 0

    def submit(self):
        self.calls += 1


def _storage(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "s"), "runs")
    storage.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return storage


def _run(tmp_path, clock, host=None, **kwargs):
    return run_module.Run(_storage(tmp_path), APP, VERSTR, 3600, install_hooks=None,
                          clock=clock, host=host or FakeHost(), random=FakeRandom(), **kwargs)


def test_duration_is_elapsed_fake_clock_plus_prior_attempts(tmp_path):
    clock = FakeClock()  # 2026-01-01T00:00:00Z
    prior = {"state": "running", "started_at": "2025-12-31T23:00:00Z"}
    run = _run(tmp_path, clock, prior_state=prior)

    clock.advance(5)

    assert run._duration() == 3605.0


def test_log_sync_is_skipped_inside_the_sync_interval_and_runs_after_it(tmp_path):
    clock = FakeClock()
    run = _run(tmp_path, clock, sync_interval_sec=30)
    run._log_sync = _Submits()

    clock.advance(29)
    run._maybe_sync()
    assert run._log_sync.calls == 0

    clock.advance(1)
    run._maybe_sync()
    assert run._log_sync.calls == 1


def test_final_upload_deadline_is_the_run_clock_plus_timeout(tmp_path):
    clock = FakeClock(monotonic=1000.0)
    run = _run(tmp_path, clock)

    deadline = run._final_deadline(10)
    assert deadline == 1010.0
    assert run._final_deadline() == 1000.0 + run_module.final_upload_timeout_sec()

    clock.advance(4)
    assert run._time_left(deadline) == 6.0
    clock.advance(10)
    assert run._time_left(deadline) == 0.0


def test_initial_state_records_host_and_pid_from_the_host_port(tmp_path):
    run = _run(tmp_path, FakeClock(), FakeHost(pid=77, hostname="pod-a"))

    assert run.pid == 77
    assert (run._state["pid"], run._state["host"]) == (77, "pod-a")


def test_run_is_inert_when_host_pid_differs_from_the_owner(tmp_path):
    host = FakeHost(pid=77)
    run = _run(tmp_path, FakeClock(), host)
    assert run._in_owner()

    host._pid = 78  # the same object, seen from a forked child

    assert not run._in_owner()


def test_start_run_hands_the_run_a_real_clock_and_host(tmp_path, monkeypatch):
    built = {}

    class _Built(Exception):
        pass

    def _capture(*args, **kwargs):
        built.update(kwargs)
        raise _Built

    monkeypatch.setattr(run_module, "Run", _capture)
    with pytest.raises(_Built):
        run_module.start_run(APP, storage=_storage(tmp_path), code=False, system_metrics=False)

    assert isinstance(built["clock"], RealClock)
    assert isinstance(built["host"], RealHost)
