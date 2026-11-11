"""`vmn-exp ui` maintenance verbs are real subcommands with their own flags
(plan 39 B8): serving stays the default, each verb takes only its flags, and
the handlers still read the `ui_args` list they read before."""
import argparse

import pytest

from vmn_exp.ui.cli_parser import add_ui_parser


def _parser():
    parser = argparse.ArgumentParser("vmn-exp")
    add_ui_parser(parser.add_subparsers(dest="command"))
    return parser


def _parse(*argv):
    return _parser().parse_args(["ui", *argv])


def _ui_help(capsys):
    with pytest.raises(SystemExit):
        _parse("--help")
    return capsys.readouterr().out


def test_bare_ui_serves_with_empty_ui_args():
    args = _parse()
    assert args.ui_args == [] and args.port == 8265 and args.host == "127.0.0.1"


def test_cache_rebuild_with_workspace_gives_todays_ui_args():
    args = _parse("cache", "rebuild", "--workspace", "ws")
    assert args.ui_args == ["cache", "rebuild"] and args.workspace == "ws"


def test_backup_path_gives_todays_ui_args():
    assert _parse("backup", "/b/cp.db").ui_args == ["backup", "/b/cp.db"]


def test_backup_without_a_path_still_reaches_the_handlers_usage_error():
    assert _parse("backup").ui_args == ["backup"]
    assert _parse("cache").ui_args == ["cache"]


def test_config_before_or_after_the_verb_is_the_same():
    before = _parse("--config", "s.yml", "cache", "rebuild")
    after = _parse("cache", "rebuild", "--config", "s.yml")
    assert before.config == after.config == "s.yml"
    assert before.ui_args == after.ui_args == ["cache", "rebuild"]


def test_a_verb_does_not_reset_a_flag_given_before_it():
    args = _parse("--data-dir", "/d", "--token", "t", "diag", "--summarize", "x.json")
    assert (args.data_dir, args.token, args.diag_summarize) == ("/d", "t", "x.json")
    assert args.ui_args == ["diag"]


def test_diag_flags_are_rejected_when_serving():
    with pytest.raises(SystemExit) as exc:
        _parse("--pid", "3")
    assert exc.value.code == 2


def test_serve_flags_are_rejected_on_onboarding():
    with pytest.raises(SystemExit) as exc:
        _parse("onboarding", "--port", "1")
    assert exc.value.code == 2


def test_an_unknown_verb_is_an_argparse_error():
    with pytest.raises(SystemExit) as exc:
        _parse("frobnicate")
    assert exc.value.code == 2


def test_ui_help_lists_the_verbs_and_no_diag_flags(capsys):
    out = _ui_help(capsys)
    for verb in ("cache", "onboarding", "backup", "diag"):
        assert verb in out
    for flag in ("--pid", "--summarize", "--account-id", "--workspace"):
        assert flag not in out


def test_diag_still_runs_without_a_repo():
    from vmn_exp.cli.plugin import _ui_run_without_repo

    seen = []
    args = _parse("diag", "--url", "http://x")
    assert _ui_run_without_repo(args, handle_ui=lambda a: seen.append(a) or 7) == 7
    assert seen == [args]
    assert _ui_run_without_repo(_parse(), handle_ui=lambda a: 7) is None
