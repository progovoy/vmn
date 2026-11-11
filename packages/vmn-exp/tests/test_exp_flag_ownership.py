"""A flag the experiment action does not own is a usage error (plan 39 B5b).

The flat parser still parses every flag on every action; ownership is checked
right after parsing, before the repo or a store is touched, and exits 2.
"""
from types import SimpleNamespace

import pytest

from test_ui_job_argv_fuzz import BENIGN
from version_stamp.cli.args import parse_user_commands
from version_stamp.core.logging import init_stamp_logger
from vmn_exp.cli.exp_parser.actions import ACTION_FLAGS
from vmn_exp.cli.exp_parser.build import flag_defaults
from vmn_exp.cli.exp_parser.ownership import foreign_flags
from vmn_exp.cli.experiment import handle_experiment
from vmn_exp.cli.plugin import _exp_run_without_repo, register_all
from vmn_exp.ui.jobs import build_command

# {dest: (option, default, group)}, as flag_defaults() gives them.
DEFAULTS = {
    "force": ("--force", False, "force"),
    "local_only": ("--local-only", False, "prune"),
    "yes": ("--yes", False, "prune"),
    "sort": ("--sort", None, "sort"),
    "store": ("--store", None, "storage"),
}
TABLE = {
    "list": ("sort", "storage"),
    "prune": ("prune", "force", "storage"),
    "show": ("storage",),
}


def _args(**values):
    return SimpleNamespace(**values)


def test_a_prune_flag_on_list_is_foreign():
    assert foreign_flags(_args(local_only=True), "list", DEFAULTS, TABLE) == ["--local-only"]


def test_an_owned_flag_is_not_foreign():
    assert foreign_flags(_args(sort="loss"), "list", DEFAULTS, TABLE) == []
    assert foreign_flags(_args(local_only=True), "prune", DEFAULTS, TABLE) == []


def test_a_flag_left_at_its_default_is_not_reported():
    args = _args(force=False, local_only=False, yes=False, sort=None)
    assert foreign_flags(args, "list", DEFAULTS, TABLE) == []


def test_storage_flags_are_owned_by_every_store_action():
    args = _args(store="s3://b/p")
    for action in TABLE:
        assert foreign_flags(args, action, DEFAULTS, TABLE) == []
    defaults = flag_defaults()
    for action in ACTION_FLAGS:
        assert foreign_flags(_args(store="s3://b/p", experiment_dir="/d", writer_id="w"),
                             action, defaults, ACTION_FLAGS) == [], action


def test_several_foreign_flags_are_all_named():
    args = _args(force=True, yes=True, local_only=True)
    assert foreign_flags(args, "show", DEFAULTS, TABLE) == ["--force", "--local-only", "--yes"]


@pytest.fixture
def logger():
    init_stamp_logger()


def _parse(*argv):
    register_all()
    return parse_user_commands(["experiment", *argv])


def _log_text(caplog, capsys):
    return caplog.text + capsys.readouterr().err


def test_list_with_force_exits_2_and_touches_nothing(tmp_path, logger):
    store = tmp_path / "store"
    args = _parse("list", "my_app", "--force", "--experiment-dir", str(store))
    assert _exp_run_without_repo(args) == 2
    assert not store.exists()


def test_create_with_latest_exits_2_before_any_record_is_written(tmp_path, logger):
    store = tmp_path / "store"
    args = _parse("create", "my_app", "--latest", "--from-snapshot", str(tmp_path),
                  "--experiment-dir", str(store))
    assert _exp_run_without_repo(args) == 2
    assert not store.exists()


def test_the_error_names_the_flag_the_action_and_its_help(tmp_path, caplog, capsys,
                                                          logger):
    args = _parse("list", "my_app", "--force", "--experiment-dir", str(tmp_path))
    assert _exp_run_without_repo(args) == 2
    assert ("'--force' is not a flag of 'vmn-exp list' (see 'vmn-exp list --help')"
            in _log_text(caplog, capsys))


def test_handle_experiment_rejects_a_foreign_flag_before_touching_the_repo(logger):
    args = _parse("show", "my_app", "--yes")
    assert handle_experiment(SimpleNamespace(vcs=None, args=args)) == 2


def _ui_job_argvs():
    for action, bodies in BENIGN.items():
        for body in bodies:
            argv, err = build_command(action, "my_app", body)
            assert err is None, (action, err)
            if argv[0] == "vmn-exp":
                yield pytest.param(argv, id=f"{action}-{'-'.join(body)}")


@pytest.mark.parametrize("argv", list(_ui_job_argvs()))
def test_no_ui_job_argv_carries_a_foreign_flag(argv):
    register_all()
    args = parse_user_commands(argv[1:])
    assert foreign_flags(args, args.action, flag_defaults(), ACTION_FLAGS) == []
