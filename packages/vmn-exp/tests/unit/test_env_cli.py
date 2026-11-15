"""The ``vmn-exp`` command handlers read the environment only through the Env
they are given (plan 44 G12 stage B)."""
import argparse
from types import SimpleNamespace

import pytest

from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import FakeProcesses
from fakes.random import FakeRandom
from version_stamp.cli.args import parse_user_commands
from vmn_exp.cli import experiment, login, run
from vmn_exp.core.ports import IO


def _io(env):
    return IO(clock=FakeClock(), env=env, processes=FakeProcesses({}),
              random=FakeRandom(), host=FakeHost(), console=FakeConsole())


def test_parent_defaults_to_VMN_EXPERIMENT_ID_of_the_given_env(monkeypatch):
    monkeypatch.setenv("VMN_EXPERIMENT_ID", "0.0.1-dev.process")
    monkeypatch.setattr(experiment, "resolve_parent",
                        lambda storage, app, explicit, env_ref: (explicit or env_ref, None))
    no_flag = argparse.Namespace(parent=None)
    env = FakeEnv({"VMN_EXPERIMENT_ID": "0.0.1-dev.given"})

    assert experiment._resolve_parent("storage", "app", no_flag, env) == ("0.0.1-dev.given", None)
    assert experiment._resolve_parent("storage", "app", no_flag, FakeEnv()) == (None, None)
    assert experiment._resolve_parent(
        "storage", "app", argparse.Namespace(parent="0.0.1-dev.flag"), env) == (
        "0.0.1-dev.flag", None)


@pytest.mark.parametrize("env, auto_inits", [
    (FakeEnv({"VMN_SNAPSHOT_METADATA": "snap.yml"}), 0),
    (FakeEnv(), 1),
])
def test_from_snapshot_env_skips_auto_init(monkeypatch, env, auto_inits):
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", "process-snap.yml")
    inits, created = [], []
    monkeypatch.setattr(experiment, "auto_init", lambda ctx: inits.append(ctx))
    monkeypatch.setattr(experiment, "_open_checked_storage", lambda *a, **k: "storage")
    monkeypatch.setattr(experiment, "experiment_create",
                        lambda *a, env, **k: created.append(env) or 0)
    io = _io(env)

    args = parse_user_commands(["exp", "create", "my_app"])
    assert experiment.handle_experiment(SimpleNamespace(vcs=None, args=args), io) == 0

    assert len(inits) == auto_inits
    assert created == [env]


def test_kill_grace_env():
    no_flag = argparse.Namespace(kill_grace_sec=None)

    assert run._kill_graces(no_flag, FakeEnv({run.KILL_GRACE_ENV: "7"}))[0] == 7
    assert run._kill_graces(no_flag, FakeEnv())[0] == run.DEFAULT_KILL_GRACE_SEC


def test_credentials_live_under_XDG_CONFIG_HOME_of_the_given_env(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/process")

    assert login.credentials_path(FakeEnv({"XDG_CONFIG_HOME": "/given"})) == (
        "/given/vmn-exp/credentials")


def test_run_login_hands_its_env_to_login(monkeypatch):
    seen = []
    monkeypatch.setattr(login, "login", lambda server, **kw: seen.append(kw["env"]) or 0)
    io = _io(FakeEnv({"XDG_CONFIG_HOME": "/given"}))

    assert login.run_login(["--server", "https://srv"], io) == 0

    assert seen == [io.env]
