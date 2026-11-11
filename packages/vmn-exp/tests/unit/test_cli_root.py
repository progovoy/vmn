"""The vmn-exp CLI's composition roots (plan 44 G7): command handlers take
``io``; only the plugin.py shims and cli/main.py build the real one."""
import ast
from pathlib import Path
from types import SimpleNamespace

from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import FakeProcesses
from fakes.random import FakeRandom
from version_stamp.cli.args import parse_user_commands
from vmn_exp.cli import experiment, login, plugin
from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.core.ports import IO
from vmn_exp.core.real_io import RealClock

CLI_DIR = Path(experiment.__file__).resolve().parent


def _fake_io(stdin=""):
    return IO(clock=FakeClock(), env=FakeEnv(), processes=FakeProcesses({}),
              random=FakeRandom(), host=FakeHost(), console=FakeConsole(stdin))


def test_handle_experiment_passes_io_to_the_action(monkeypatch):
    got = []
    monkeypatch.setattr(experiment, "_open_checked_storage", lambda *a, **k: "storage")
    monkeypatch.setattr(experiment, "experiment_run",
                        lambda *a, io, **k: got.append(io) or 0)
    args = parse_user_commands(["exp", "run", "my_app", "--from-snapshot", "snap", "--", "true"])
    io = _fake_io()
    assert experiment.handle_experiment(SimpleNamespace(vcs=None, args=args), io) == 0
    assert got == [io]


def test_plugin_shim_builds_real_io_once_per_invocation(monkeypatch):
    got = []
    monkeypatch.setattr(experiment, "handle_experiment",
                        lambda ctx, io: got.append(io) or 0)
    ctx = SimpleNamespace(vcs=None, args=None)
    assert plugin._handle_experiment(ctx) == 0
    assert plugin._handle_experiment(ctx) == 0
    assert [type(io.clock) for io in got] == [RealClock, RealClock]
    assert got[0] is not got[1]


def test_login_receives_io(monkeypatch):
    start = {"verification_uri": "https://idp/device", "user_code": "ABCD",
             "device_code": "dc", "interval": 0, "expires_in": 0}
    monkeypatch.setattr(login, "urllib_post_json", lambda url, body: (200, start))
    io = _fake_io()
    assert login.run_login(["--server", "https://srv"], io) == 1
    assert "Open https://idp/device and enter the code ABCD" in io.console.stderr
    assert io.console.stdout == ""


def test_wrong_command_hint_goes_to_stderr_with_exit_code_2():
    io = _fake_io()
    code, _ = vmn_exp_run(["stamp"], io)
    assert code == 2
    assert "run 'vmn stamp' for that" in io.console.stderr
    assert io.console.stdout == ""


def _calls_real_io(path):
    return any(
        isinstance(node, ast.Call) and getattr(node.func, "id", None) == "real_io"
        for node in ast.walk(ast.parse(path.read_text()))
    )


def test_no_handler_module_calls_real_io():
    callers = {path.relative_to(CLI_DIR).as_posix()
               for path in CLI_DIR.rglob("*.py") if _calls_real_io(path)}
    assert callers == {"plugin.py", "main.py"}
