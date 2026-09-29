"""``--prefix`` has no literal default: an unset prefix is None, so an
explicit ``--prefix vmn-experiments`` is a real choice that env/conf never
override, and the store URI alone supplies the default prefix."""
from types import SimpleNamespace

import pytest

from version_stamp.cli.args import parse_user_commands
from vmn_exp.core.writer import merge_conf_into_params, merge_env_into_params


@pytest.mark.parametrize("argv", [
    ["exp", "list", "app"],
    ["sweep", "status", "app"],
    ["model", "list"],
])
def test_prefix_flag_defaults_to_unset(argv):
    assert parse_user_commands(argv).prefix is None


def test_an_explicit_default_prefix_beats_the_env(monkeypatch):
    monkeypatch.setenv("VMN_EXPERIMENT_PREFIX", "from-env")
    params = {"bucket": "b", "prefix": "vmn-experiments"}
    merge_env_into_params(params)
    assert params["prefix"] == "vmn-experiments"


def test_an_explicit_default_prefix_beats_the_conf(monkeypatch):
    monkeypatch.delenv("VMN_EXPERIMENT_PREFIX", raising=False)
    vcs = SimpleNamespace(experiment={"storage": {"prefix": "from-conf"}})
    params = {"bucket": "b", "prefix": "vmn-experiments"}
    merge_conf_into_params(vcs, params)
    assert params["prefix"] == "vmn-experiments"
