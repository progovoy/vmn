"""The exit-code contract (plan 39 B7): 0 success, 1 the command ran and
failed, 2 the invocation was wrong. Handler-detected usage errors return 2
like argparse does; a run that is not there is a failure, not a usage error.
"""
from types import SimpleNamespace

import pytest

from version_stamp.cli.args import parse_user_commands
from version_stamp.core.logging import init_stamp_logger
from vmn_exp.cli.experiment import handle_experiment
from vmn_exp.cli.plugin import _exp_run_without_repo, register_all
from vmn_exp.cli.run import experiment_run
from vmn_exp.cli.run_disabled import exec_if_disabled
from vmn_exp.cli.settings import settings_run_without_repo


@pytest.fixture(autouse=True)
def logger():
    init_stamp_logger()


def _parse(*argv):
    register_all()
    return parse_user_commands(["experiment", *argv])


def test_settings_set_without_a_file_is_a_usage_error(tmp_path):
    args = SimpleNamespace(action="set", name="my_app", file=None, dir=str(tmp_path),
                           store=None, bucket=None, prefix=None, endpoint_url=None)
    assert settings_run_without_repo(args) == 2


def test_run_without_a_command_is_a_usage_error():
    assert experiment_run(None, None, None, SimpleNamespace(run_cmd=None)) == 2


def test_run_without_a_command_is_a_usage_error_when_disabled(monkeypatch):
    monkeypatch.setenv("VMN_MODE", "disabled")
    assert exec_if_disabled(SimpleNamespace(run_cmd=None)) == 2


def test_stray_refs_are_a_usage_error():
    args = _parse("list", "my_app", "stray")
    assert handle_experiment(SimpleNamespace(vcs=None, args=args)) == 2


def test_stray_refs_are_a_usage_error_without_a_repo(tmp_path):
    store = tmp_path / "store"
    args = _parse("show", "my_app", "stray", "--from-snapshot", str(tmp_path),
                  "--experiment-dir", str(store))
    assert _exp_run_without_repo(args) == 2
    assert not store.exists()


def test_refs_on_a_manage_action_are_not_stray(tmp_path):
    args = _parse("tag", "my_app", "@1", "stage=prod", "--from-snapshot", str(tmp_path),
                  "--experiment-dir", str(tmp_path / "store"))
    assert _exp_run_without_repo(args) != 2


def test_a_missing_run_is_a_failure_not_a_usage_error(tmp_path):
    args = _parse("show", "my_app", "-v", "0.0.1-dev.0123456789ab.r1",
                  "--from-snapshot", str(tmp_path), "--experiment-dir", str(tmp_path / "s"))
    assert _exp_run_without_repo(args) == 1
