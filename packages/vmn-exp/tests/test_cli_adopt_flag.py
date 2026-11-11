"""Whether ``vmn-exp run`` offers its run to the child: ``--no-adopt`` and
``VMN_EXP_ADOPT`` (plan 38 A4)."""
import argparse

import pytest

from vmn_exp.cli.plugin import _add_experiment_parser
from vmn_exp.cli.supervised_env import adopt_requested


def test_adopt_is_requested_by_default():
    assert adopt_requested(argparse.Namespace(adopt_run=True), {}) is True


def test_args_without_the_attribute_request_adoption():
    assert adopt_requested(argparse.Namespace(), {}) is True


def test_no_adopt_flag_turns_it_off():
    assert adopt_requested(argparse.Namespace(adopt_run=False), {}) is False


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "FALSE", "Off", " no "])
def test_vmn_exp_adopt_0_false_no_off_turn_it_off(value):
    assert adopt_requested(argparse.Namespace(), {"VMN_EXP_ADOPT": value}) is False


@pytest.mark.parametrize("value", ["1", "true", "yes", ""])
def test_other_vmn_exp_adopt_values_keep_it_on(value):
    assert adopt_requested(argparse.Namespace(), {"VMN_EXP_ADOPT": value}) is True


def _experiment_parser():
    sub = argparse.ArgumentParser().add_subparsers(dest="command")
    _add_experiment_parser(sub, "experiment")
    return sub.choices["experiment"]


def test_the_parser_turns_adoption_on_by_default_and_off_with_no_adopt():
    parser = _experiment_parser()
    assert parser.parse_args(["run", "app"]).adopt_run is True
    assert parser.parse_args(["run", "app", "--no-adopt"]).adopt_run is False


def test_no_adopt_leaves_push_adopt_alone():
    parser = _experiment_parser()
    assert parser.parse_args(["run", "app", "--no-adopt"]).adopt is False
    assert parser.parse_args(["push", "app", "--adopt"]).adopt_run is True
