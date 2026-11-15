"""Each shared fake in tests/fakes/ passes the same contract as the real
implementation in vmn_exp.core.real_io, so the fakes cannot drift from it."""
import io
import secrets
import subprocess
import sys
from collections.abc import Mapping
from datetime import timedelta

import pytest

from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import HANG, FakeProcesses
from fakes.random import FakeRandom
from vmn_exp.core import ports, real_io

OK = [sys.executable, "-c", "print('hi')"]
SLOW = [sys.executable, "-c", "import time; time.sleep(5)"]
MISSING = ["vmn-ports-contract-no-such-binary"]


@pytest.fixture(params=["fake", "real"])
def side(request):
    return request.param


def test_clock_contract(side):
    clock = FakeClock() if side == "fake" else real_io.RealClock()
    first = clock.monotonic()
    assert clock.monotonic() >= first
    now = clock.now()
    assert now.utcoffset() == timedelta(0) and now.tzinfo is not None
    assert clock.sleep(0) is None


def test_fake_clock_sleep_advances_monotonic_and_now_together():
    clock = FakeClock()
    mono, now = clock.monotonic(), clock.now()
    clock.sleep(2.5)
    assert clock.monotonic() == mono + 2.5
    assert clock.now() == now + timedelta(seconds=2.5)


def _processes(side):
    if side == "fake":
        return FakeProcesses({
            tuple(OK): subprocess.CompletedProcess(OK, 0, stdout="hi\n", stderr=""),
            tuple(SLOW): HANG,
        })
    return real_io.RealProcesses()


def test_processes_contract(side):
    processes = _processes(side)
    done = processes.run(OK, capture_output=True, text=True)
    assert (done.returncode, done.stdout) == (0, "hi\n")
    with pytest.raises(subprocess.TimeoutExpired):
        processes.run(SLOW, timeout=0.05)
    assert processes.run(MISSING) is None


@pytest.mark.real_io
def test_real_processes_missing_cwd_still_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        real_io.RealProcesses().run(OK, cwd=tmp_path / "gone")


def test_processes_popen_contract(side):
    processes = _processes(side)
    child = processes.popen(OK, stdout=subprocess.PIPE, text=True)
    assert child.communicate()[0] == "hi\n"
    assert child.wait() == 0
    with pytest.raises(FileNotFoundError):
        processes.popen(MISSING)


def test_fake_processes_records_its_calls():
    processes = _processes("fake")
    processes.run(OK, text=True)
    assert processes.calls == [(OK, {"text": True})]


def test_random_contract(side):
    rnd = FakeRandom() if side == "fake" else real_io.RealRandom()
    hex_id = rnd.hex_id()
    assert len(hex_id) == 32 and int(hex_id, 16) >= 0
    assert len(rnd.token_hex(4)) == 8
    assert len(rnd.token_bytes(5)) == 5 and isinstance(rnd.token_bytes(5), bytes)
    assert isinstance(rnd.token_urlsafe(8), str) and rnd.token_urlsafe(8)
    assert rnd.hex_id() != hex_id


def test_real_random_is_backed_by_secrets(monkeypatch):
    monkeypatch.setattr(secrets, "token_bytes", lambda n: b"\x01" * n)
    rnd = real_io.RealRandom()
    assert rnd.hex_id() == "01" * 16
    assert rnd.token_hex(2) == "0101"
    assert rnd.token_bytes(3) == b"\x01" * 3
    assert rnd.token_urlsafe(3) == "AQEB"


def test_host_contract(side):
    host = FakeHost() if side == "fake" else real_io.RealHost()
    assert isinstance(host.pid(), int) and host.pid() > 0
    assert isinstance(host.hostname(), str) and host.hostname()


def test_env_contract(side, monkeypatch):
    if side == "fake":
        env = FakeEnv({"VMN_PORTS_CONTRACT": "x"})
    else:
        monkeypatch.setenv("VMN_PORTS_CONTRACT", "x")
        monkeypatch.delenv("VMN_PORTS_MISSING", raising=False)
        env = real_io.RealEnv()
    assert isinstance(env, Mapping)
    assert env["VMN_PORTS_CONTRACT"] == "x" and "VMN_PORTS_CONTRACT" in env
    assert env.get("VMN_PORTS_MISSING", "d") == "d" and "VMN_PORTS_MISSING" not in env
    with pytest.raises(TypeError):
        env["VMN_PORTS_CONTRACT"] = "y"


def test_console_contract(side, monkeypatch, capsys):
    if side == "fake":
        console = FakeConsole(stdin="yes\n")
        written = lambda: (console.stdout, console.stderr)  # noqa: E731
    else:
        monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))
        console = real_io.RealConsole()
        written = lambda: tuple(capsys.readouterr())  # noqa: E731
    console.out("a")
    console.err("b")
    assert written() == ("a\n", "b\n")
    assert console.read_line() == "yes"
    assert console.read_line() == ""


def test_real_console_writes_to_the_current_sys_stdout(monkeypatch):
    console = real_io.RealConsole()
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    console.out("a")
    console.err("b")
    assert (out.getvalue(), err.getvalue()) == ("a\n", "b\n")


def test_real_io_bundles_the_real_implementations():
    bundle = real_io.real_io()
    assert isinstance(bundle, ports.IO)
    assert [type(part) for part in (bundle.clock, bundle.env, bundle.processes,
                                    bundle.random, bundle.host, bundle.console)] == [
        real_io.RealClock, real_io.RealEnv, real_io.RealProcesses,
        real_io.RealRandom, real_io.RealHost, real_io.RealConsole,
    ]

