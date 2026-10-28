"""``vmn-exp ui --keep-warm/--no-keep-warm`` and server.yml's
``server.keep_warm``: flag > file > the default (None: store workspaces
kept warm, checkouts not), handed to the server's refresher."""
import pytest

pytest.importorskip("fastapi")

from test_ui_cli import _run_handle_ui
from test_ui_server_config import _args, _write
from vmn_exp.ui.config import ConfigError, load_config, resolve_config


def test_keep_warm_defaults_to_none(tmp_path):
    assert load_config(_write(tmp_path, "")).server.keep_warm is None


@pytest.mark.parametrize("value", [True, False])
def test_server_keep_warm_parses(tmp_path, value):
    cfg = load_config(_write(tmp_path, f"server: {{keep_warm: {str(value).lower()}}}\n"))
    assert cfg.server.keep_warm is value


def test_server_keep_warm_must_be_a_bool(tmp_path):
    with pytest.raises(ConfigError, match="server.keep_warm"):
        load_config(_write(tmp_path, "server: {keep_warm: maybe}\n"))


def test_the_flag_beats_the_file(tmp_path):
    path = _write(tmp_path, "server: {keep_warm: true}\n")
    assert resolve_config(_args(config=path, keep_warm=False), env={}).server.keep_warm is False
    assert resolve_config(_args(config=path, keep_warm=None), env={}).server.keep_warm is True


@pytest.mark.parametrize("argv, expected", [
    ([], None), (["--keep-warm"], True), (["--no-keep-warm"], False)])
def test_the_flag_parses(argv, expected):
    from version_stamp.cli.args import parse_user_commands

    assert parse_user_commands(["ui"] + argv).keep_warm is expected


def _served_keep_warm(tmp_path, monkeypatch, extra):
    rc, calls = _run_handle_ui(tmp_path, monkeypatch, extra)
    assert rc == 0
    app = calls[0][0][0]
    try:
        return app.state.refresher.keep_warm
    finally:
        app.state.refresher.stop()


@pytest.mark.parametrize("extra, expected", [
    ([], None), (["--keep-warm"], True), (["--no-keep-warm"], False)])
def test_the_server_refresher_gets_the_flag(tmp_path, monkeypatch, extra, expected):
    assert _served_keep_warm(tmp_path, monkeypatch, extra) is expected


def test_the_server_refresher_gets_the_config(tmp_path, monkeypatch):
    path = _write(tmp_path, "server: {keep_warm: false}\n")
    assert _served_keep_warm(tmp_path, monkeypatch, ["--config", path]) is False
    assert _served_keep_warm(tmp_path, monkeypatch, ["--config", path, "--keep-warm"]) is True
