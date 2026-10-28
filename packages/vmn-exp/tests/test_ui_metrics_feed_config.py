"""``vmn-exp ui --metrics-ended-hours`` and server.yml's
``server.metrics_ended_hours``: how long an ended outer run stays on
``/metrics`` (plan 28 T2a); flag > file > 24 h."""
import pytest

pytest.importorskip("fastapi")

from test_ui_cli import _run_handle_ui
from test_ui_server_config import _args, _write
from vmn_exp.ui.config import ConfigError, load_config, resolve_config


def test_the_window_defaults_to_a_day(tmp_path):
    assert load_config(_write(tmp_path, "")).server.metrics_ended_hours == 24


def test_the_window_parses(tmp_path):
    cfg = load_config(_write(tmp_path, "server: {metrics_ended_hours: 6}\n"))
    assert cfg.server.metrics_ended_hours == 6


@pytest.mark.parametrize("bad", ["0", "-1", "soon", "1.5"])
def test_the_window_must_be_a_positive_integer(tmp_path, bad):
    with pytest.raises(ConfigError, match="server.metrics_ended_hours"):
        load_config(_write(tmp_path, f"server: {{metrics_ended_hours: {bad}}}\n"))


def test_the_flag_beats_the_file(tmp_path):
    path = _write(tmp_path, "server: {metrics_ended_hours: 6}\n")
    hours = lambda flag: resolve_config(  # noqa: E731
        _args(config=path, metrics_ended_hours=flag), env={}).server.metrics_ended_hours
    assert hours(48) == 48 and hours(None) == 6


@pytest.mark.parametrize("argv, expected", [([], None), (["--metrics-ended-hours", "3"], 3)])
def test_the_flag_parses(argv, expected):
    from version_stamp.cli.args import parse_user_commands

    assert parse_user_commands(["ui"] + argv).metrics_ended_hours == expected


def _served_hours(tmp_path, monkeypatch, extra):
    rc, calls = _run_handle_ui(tmp_path, monkeypatch, extra)
    assert rc == 0
    app = calls[0][0][0]
    try:
        return app.state.metrics_feed.ended_hours
    finally:
        app.state.refresher.stop()


@pytest.mark.parametrize("extra, expected", [([], 24), (["--metrics-ended-hours", "3"], 3)])
def test_the_server_gets_the_flag(tmp_path, monkeypatch, extra, expected):
    assert _served_hours(tmp_path, monkeypatch, extra) == expected


def test_the_server_gets_the_config(tmp_path, monkeypatch):
    path = _write(tmp_path, "server: {metrics_ended_hours: 2}\n")
    assert _served_hours(tmp_path, monkeypatch, ["--config", path]) == 2


def test_a_non_positive_flag_is_refused():
    from version_stamp.cli.args import parse_user_commands

    with pytest.raises(SystemExit):
        parse_user_commands(["ui", "--metrics-ended-hours", "0"])
