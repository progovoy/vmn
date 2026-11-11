"""vmn-exp's own prog name, version and command list (plan 39 B1).

In-process ``run_argv`` with a fake version reader: no repo, no git.
"""
import re

import pytest

from vmn_exp.cli.main import _to_vmn_argv, run_argv
from vmn_exp.cli.version import display_version

FAKE_VERSION = "7.7.7-fake"


def _fake_reader():
    return FAKE_VERSION


def _exit_output(capsys, argv):
    with pytest.raises(SystemExit) as exc:
        run_argv(argv, _fake_reader)
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_help_says_vmn_exp_and_lists_no_stamping_commands(capsys):
    out = _exit_output(capsys, ["--help"])
    assert out.startswith("usage: vmn-exp ")
    commands = set(re.search(r"\{([a-z,_-]+)\}", out).group(1).split(","))
    assert commands == {"experiment", "exp", "model", "report", "comment", "comments",
                        "settings", "sweep", "ui"}


def test_help_names_skill_migrate_and_login(capsys):
    out = _exit_output(capsys, ["--help"])
    for intercepted in ("skill", "migrate", "login"):
        assert re.search(rf"\b{intercepted}\b", out), intercepted


def test_version_prints_only_the_vmn_exp_version(capsys):
    from version_stamp.api import version as core_version

    out = _exit_output(capsys, ["--version"])
    assert out == f"{FAKE_VERSION}\n"
    assert core_version.version not in out


def test_ui_help_usage_starts_with_vmn_exp_ui(capsys):
    assert _exit_output(capsys, ["ui", "--help"]).startswith("usage: vmn-exp ui")


def test_stamp_still_points_at_vmn_with_exit_2(capsys):
    code, _ = run_argv(["stamp", "-r", "patch", "app"], _fake_reader)
    assert code == 2
    assert "vmn stamp" in capsys.readouterr().err


def test_display_version_returns_the_readers_string():
    assert display_version(_fake_reader) == FAKE_VERSION


def test_display_version_without_installed_metadata_says_unknown():
    assert display_version(lambda: None) == "unknown"


def test_debug_before_a_bare_action_still_routes_to_exp():
    assert _to_vmn_argv(["--debug", "run", "app", "--", "true"]) == [
        "--debug", "exp", "run", "app", "--", "true"]


def test_debug_before_an_own_command_is_left_alone():
    assert _to_vmn_argv(["--debug", "model", "list"]) == ["--debug", "model", "list"]


def test_help_and_version_pass_through():
    for flag in ("--help", "-h", "--version", "-v", "--completion"):
        assert _to_vmn_argv([flag]) == [flag]
    assert _to_vmn_argv(["--debug", "--help"]) == ["--debug", "--help"]


def test_debug_stamp_still_hits_the_stamping_guard(capsys):
    code, _ = run_argv(["--debug", "stamp", "-r", "patch", "app"], _fake_reader)
    assert code == 2
    assert "vmn stamp" in capsys.readouterr().err
