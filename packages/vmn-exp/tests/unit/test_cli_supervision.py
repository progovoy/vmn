"""``vmn-exp run`` supervision on injected IO (plan 44 G8): the clock, the
child's env and start, the host and the kill grace come from ``io``."""
import argparse
import subprocess

import pytest

from empty_storage import EmptyStorage
from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import FakeProcesses
from fakes.random import FakeRandom
from vmn_exp.cli import run as run_mod
from vmn_exp.cli.run import KILL_GRACE_ENV, DEFAULT_KILL_GRACE_SEC, _Supervision
from vmn_exp.cli.supervisor import SignalForwarder
from vmn_exp.cli.supervisor_state import SIGNAL_CHILD_GRACE_SEC
from vmn_exp.core.ports import IO
from version_stamp.core.logging import init_stamp_logger

VERSTR = "1.0.0-dev.abc.r1"
CMD = ("train",)


@pytest.fixture(autouse=True)
def logger():
    init_stamp_logger()


def _io(env=None, clock=None, script=None):
    return IO(clock=clock or FakeClock(), env=FakeEnv(env), processes=FakeProcesses(script),
              random=FakeRandom(), host=FakeHost(), console=FakeConsole(""))


def _args(**over):
    base = dict(capture_output=False, kill_grace_sec=None, system_metrics=False)
    base.update(over)
    return argparse.Namespace(**base)


class _Uploads:
    """StateUploads' surface: records each publish, failing the first *fail*."""

    def __init__(self, fail=0):
        self.published, self._fail = [], fail
        self.last_error = None

    def publish(self, run_state, final=False):
        if self._fail:
            self._fail -= 1
            raise OSError("bucket down")
        self.published.append(dict(run_state))

    def close(self, timeout):
        return True


class _Sync:
    def __init__(self):
        self.requests, self.finals = 0, []

    def request(self, *_):
        self.requests += 1

    def final(self, timeout):
        self.finals.append(timeout)


class _Tailer:
    def poll(self):
        return []


class _Sampler:
    def tick(self):
        pass


class _Child:
    """A child that lives for *waits* calls of ``wait(timeout)``, each one
    advancing *clock* by the timeout."""

    pid = 777

    def __init__(self, clock, waits=0):
        self.clock, self.waits, self.returncode = clock, waits, None
        self.killed = False
        if waits == 0:
            self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None and self.waits:
            self.waits -= 1
            self.clock.advance(timeout)
            if self.waits:
                raise subprocess.TimeoutExpired(CMD, timeout)
            self.returncode = 0
        return self.returncode

    def send_signal(self, _signum):
        pass

    def kill(self):
        self.killed = True


def _supervision(io, on_tick=None, **args_over):
    sup = _Supervision(EmptyStorage(), "app", VERSTR, _args(**args_over), cwd="/work",
                       on_tick=on_tick, wait=lambda _sec: False, io=io)
    sup.state_uploads = _Uploads()
    sup.sync = _Sync()
    sup.tailer = _Tailer()
    sup.metrics_path = "/tmp/metrics"
    sup.samples_tree = False
    sup.run_state = {"heartbeat_seq": 0}
    return sup


def _tick(sup, start, sync_interval=0, heartbeat_interval=10):
    return sup._tick(_Sampler(), sync_interval, heartbeat_interval, start)


def test_heartbeat_is_published_once_per_interval():
    sup = _supervision(_io())
    tick = _tick(sup, 1000.0, heartbeat_interval=10)
    for now in (1005.0, 1010.0, 1015.0, 1020.0):
        tick(now)
    assert [s["heartbeat_seq"] for s in sup.state_uploads.published] == [1, 2]


def test_sync_is_requested_after_sync_interval_and_not_before():
    sup = _supervision(_io())
    tick = _tick(sup, 1000.0, sync_interval=5, heartbeat_interval=100)
    seen = []
    for now in (1003.0, 1006.0, 1010.0, 1012.0):
        tick(now)
        seen.append(sup.sync.requests)
    assert seen == [0, 1, 1, 2]


def test_final_state_write_is_retried_with_one_second_sleeps():
    waits = []
    sup = _Supervision(EmptyStorage(), "app", VERSTR, _args(), cwd="/work",
                       wait=lambda sec: waits.append(sec) or False, io=_io())
    sup.state_uploads = _Uploads(fail=2)
    sup.run_state = {}
    sup._publish_final({"state": "finished"})
    assert waits == [1, 1]
    assert sup.state_uploads.published == [{"state": "finished"}]


def test_child_env_is_built_from_the_given_env_not_the_process_env():
    io = _io(env={"ONLY_IN_FAKE": "1"},
             script={CMD: subprocess.CompletedProcess(list(CMD), 0)})
    sup = _supervision(io)
    sup.adopt = True
    assert sup._start(list(CMD)) is not None
    cmd, kwargs = io.processes.calls[-1]
    assert cmd == list(CMD) and kwargs["cwd"] == "/work"
    assert kwargs["env"]["ONLY_IN_FAKE"] == "1"
    assert kwargs["env"]["VMN_EXPERIMENT_ID"] == VERSTR
    assert kwargs["env"]["VMN_EXP_ADOPT_PID"] == str(FakeHost().pid())


def test_command_not_found_returns_1_and_publishes_no_run_state():
    sup = _supervision(_io(script={}))
    assert sup.run(list(CMD)) == 1
    assert sup.state_uploads.published == []


def test_kill_grace_reads_the_given_env_then_the_default():
    given = _supervision(_io(env={KILL_GRACE_ENV: "7"})).forwarder
    assert (given.grace_sec, given.signal_grace_sec) == (7, 7)
    default = _supervision(_io(env={})).forwarder
    assert (default.grace_sec, default.signal_grace_sec) == (
        DEFAULT_KILL_GRACE_SEC, SIGNAL_CHILD_GRACE_SEC)


def test_child_cwd_reads_vmn_working_dir_from_the_given_env():
    sup = _Supervision(EmptyStorage(), "app", VERSTR, _args(), wait=lambda _sec: False,
                       io=_io(env={"VMN_WORKING_DIR": "/invoked/here"}))
    assert sup.cwd == "/invoked/here"


def test_signal_forwarder_kills_after_the_grace_on_the_given_clock():
    clock = FakeClock()
    child = _Child(clock, waits=99)
    forwarder = SignalForwarder(5, 3, clock.monotonic)
    forwarder.attach(child)
    forwarder.request_stop()
    clock.advance(4.9)
    forwarder.enforce_grace()
    assert not child.killed
    clock.advance(0.1)
    forwarder.enforce_grace()
    assert child.killed


def test_run_state_host_comes_from_the_host_port():
    sup = _supervision(_io())
    sup._supervise(_Child(FakeClock()), list(CMD))
    first = sup.state_uploads.published[0]
    assert first["host"] == "fake-host" and first["pid"] == _Child.pid


def test_supervise_ticks_on_the_given_clock():
    clock = FakeClock()
    sup = _supervision(_io(clock=clock), heartbeat_interval=5)
    sup._supervise(_Child(clock, waits=25), list(CMD))  # 12.5 fake seconds
    assert [s["heartbeat_seq"] for s in sup.state_uploads.published] == [0, 1, 2]


def test_on_tick_hook_is_called_each_tick_and_its_error_is_guarded():
    calls = []

    def hook(supervision):
        calls.append(supervision)
        raise RuntimeError("hook broke")

    sup = _supervision(_io(), on_tick=hook)
    tick = _tick(sup, 1000.0)
    tick(1001.0)
    tick(1002.0)
    assert calls == [sup, sup]


def test_final_uploads_budget_starts_on_the_given_clock():
    clock = FakeClock(monotonic=1000.0)
    sup = _supervision(_io(clock=clock))
    assert sup._finish_uploads() == 1000.0 + run_mod._FINAL_SYNC_TIMEOUT_SEC
    assert sup.sync.finals == [run_mod._FINAL_SYNC_TIMEOUT_SEC]


def test_duration_is_measured_on_the_given_clock():
    clock = FakeClock()
    sup = _supervision(_io(clock=clock))
    sup.start = clock.monotonic()
    clock.advance(12.5)
    sup._finish(_Child(clock), list(CMD))
    assert sup.state_uploads.published[-1]["duration_sec"] == 12.5


def test_from_snapshot_is_read_from_the_given_env(monkeypatch):
    import vmn_exp.cli.experiment as cli

    got = {}
    monkeypatch.setattr(cli, "_app_name", lambda vcs, args: "app")
    monkeypatch.setattr(cli, "_resolve_parent", lambda *a: (None, None))
    monkeypatch.setattr(run_mod.fork, "fork_source", lambda *a: (None, None))
    monkeypatch.setattr(run_mod.fork, "seed", lambda *a: None)
    monkeypatch.setattr(cli, "_experiment_create_core",
                        lambda vcs, storage, **kw: (got.update(kw), (VERSTR, None))[1])
    args = argparse.Namespace(note=None, from_snapshot=None)
    run_mod._create_experiment(None, EmptyStorage(), args,
                               env=FakeEnv({"VMN_SNAPSHOT_METADATA": "/snap.yml"}), host=FakeHost())
    assert got["from_snapshot"] == "/snap.yml"


def test_the_run_log_entry_is_appended_as_the_supervisions_writer():
    sup = _supervision(_io(env={"VMN_WRITER_ID": "pod-3"}))
    calls = {}
    sup.guard = lambda what, fn, *args: calls.setdefault(what, (fn, args))
    sup.start = 0.0
    sup.output = None
    sup._finish(_Child(FakeClock()), list(CMD))
    fn, args = calls["run log entry"]
    assert fn is run_mod.append_to_log
    assert args[-1] == "pod-3"
