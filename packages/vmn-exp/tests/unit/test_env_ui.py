"""The ``vmn-exp ui`` commands read the environment only through the Env they
are given (plan 44 G12 stage A): handle_ui hands its io.env down, and the
config and token resolution have no ``os.environ`` fallback."""
import argparse

import pytest

from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import FakeProcesses
from fakes.random import FakeRandom
from vmn_exp.core.ports import IO
from vmn_exp.ui import backup_cli, cache_cli, diag_cli
from vmn_exp.ui.cli import build_server, handle_ui
from vmn_exp.ui.config import ServerConfig, resolve_config, static_token


def _io(env):
    return IO(clock=FakeClock(), env=env, processes=FakeProcesses(),
              random=FakeRandom(), host=FakeHost(), console=FakeConsole())


def _args(**kw):
    base = dict(config=None, db=None, host="127.0.0.1", port=8265, data_dir=None,
                token=None, keep_warm=None, metrics_ended_hours=None)
    return argparse.Namespace(**{**base, **kw})


def test_token_comes_from_the_given_env(monkeypatch):
    monkeypatch.setenv("VMN_UI_TOKEN", "from-the-process")
    env = FakeEnv({"VMN_UI_TOKEN": "from-the-given-env"})

    assert static_token(None, _args(), env) == "from-the-given-env"
    assert static_token(None, _args(), FakeEnv()) is None
    assert static_token(None, _args(token="flag"), env) == "flag"
    assert ServerConfig().token(FakeEnv()) is None
    assert ServerConfig().token(env) == "from-the-given-env"
    with pytest.raises(TypeError):
        ServerConfig().token()


def test_server_config_reads_only_the_given_env(monkeypatch):
    monkeypatch.setenv("VMN_UI_DB", "sqlite:///from-the-process")
    env = FakeEnv({"VMN_UI_DB": "sqlite:///given", "VMN_UI_DATA_DIR": "/given/data",
                   "VMN_UI_PUBLIC_URL": "https://given.example"})

    cfg = resolve_config(_args(), env)

    assert (cfg.db, cfg.data_dir, cfg.server.public_url) == (
        "sqlite:///given", "/given/data", "https://given.example")
    assert resolve_config(_args(), FakeEnv()) is None
    with pytest.raises(TypeError):
        resolve_config(_args())
    with pytest.raises(TypeError):
        build_server(_args())


@pytest.mark.parametrize("action, module, handler", [
    ("diag", diag_cli, "handle_diag"),
    ("backup", backup_cli, "handle_backup"),
    ("cache", cache_cli, "handle_cache"),
])
def test_handle_ui_hands_its_env_to_the_subcommands(monkeypatch, action, module, handler):
    seen = []
    monkeypatch.setattr(module, handler, lambda args, env: seen.append(env) or 0)
    io = _io(FakeEnv({"VMN_UI_TOKEN": "t"}))

    assert handle_ui(argparse.Namespace(ui_args=[action]), io) == 0

    assert seen == [io.env]
