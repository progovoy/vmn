"""``vmn-exp <action> --help`` lists only that action's flags (plan 39 B5d).

Help only: parsing stays on the flat parser, and ``vmn-exp exp --help`` keeps
every flag.
"""
import pytest

from vmn_exp.cli.exp_parser.actions import EXPERIMENT_ACTIONS
from vmn_exp.cli.exp_parser.help import help_action
from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.core.real_io import real_io


def test_an_action_with_help_names_the_action():
    assert help_action(["exp", "list", "my_app", "--help"]) == "list"
    assert help_action(["experiment", "show", "-h"]) == "show"


def test_help_after_a_double_dash_belongs_to_the_child():
    assert help_action(["exp", "run", "my_app", "--", "python", "train.py", "--help"]) is None


def test_exp_help_without_an_action_is_the_full_help():
    assert help_action(["exp", "--help"]) is None
    assert help_action(["--help"]) is None
    assert help_action(["exp", "--json", "list", "--help"]) is None


def test_debug_before_the_action_is_skipped():
    assert help_action(["--debug", "exp", "prune", "--help"]) == "prune"


def test_a_bare_app_name_is_not_an_action():
    assert help_action(["exp", "my_app", "--help"]) is None
    assert help_action(["model", "list", "--help"]) is None


def _help(capsys, *argv):
    with pytest.raises(SystemExit) as exc:
        vmn_exp_run(list(argv), real_io())
    return exc.value.code, capsys.readouterr().out


def test_list_help_names_sort_and_not_keep(capsys):
    _, out = _help(capsys, "list", "--help")
    assert "--sort" in out
    assert "--keep" not in out


def test_action_help_usage_reads_vmn_exp_action(capsys):
    _, out = _help(capsys, "list", "--help")
    assert out.startswith("usage: vmn-exp list ")


def test_action_help_exits_0_like_argparse(capsys):
    code, _ = _help(capsys, "exp", "show", "my_app", "-h")
    assert code == 0


def test_exp_help_still_lists_every_flag(capsys):
    _, out = _help(capsys, "exp", "--help")
    for flag in ("--sort", "--keep", "--bucket", "--max-bytes", "--fork-from"):
        assert flag in out, flag


@pytest.mark.parametrize("action", EXPERIMENT_ACTIONS)
def test_every_action_has_help(capsys, action):
    code, out = _help(capsys, action, "--help")
    assert code == 0
    assert out.startswith(f"usage: vmn-exp {action} ")
    assert "--bucket" in out
