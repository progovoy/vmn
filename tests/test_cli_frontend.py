"""parse_user_commands under a Frontend: who the CLI says it is (plan 39 B1)."""
import pytest

from version_stamp.cli.args import parse_user_commands
from version_stamp.cli.plugin_api import Frontend
from version_stamp.core import dev_build


def _output_of(capsys, argv, frontend=None):
    with pytest.raises(SystemExit) as exc:
        parse_user_commands(argv, frontend)
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_default_frontend_keeps_vmn_prog_version_and_builtins(capsys):
    assert _output_of(capsys, ["--version"]).strip() == dev_build.display_version()
    help_text = _output_of(capsys, ["--help"])
    assert help_text.startswith("usage: vmn ")
    assert "stamp" in help_text
    assert parse_user_commands(["show", "app"], Frontend()).command == "show"


def test_frontend_prog_version_and_epilog_replace_vmns(capsys):
    frontend = Frontend(prog="other", version="9.9.9", epilog="the epilog line")
    assert _output_of(capsys, ["--version"], frontend).strip() == "9.9.9"
    help_text = _output_of(capsys, ["--help"], frontend)
    assert help_text.startswith("usage: other ")
    assert "the epilog line" in help_text


def test_frontend_without_builtins_does_not_know_stamp(capsys):
    with pytest.raises(SystemExit) as exc:
        parse_user_commands(["stamp", "-r", "patch", "app"], Frontend(builtins=False))
    assert exc.value.code == 2
    assert "invalid choice: 'stamp'" in capsys.readouterr().err
