"""The experiment parser's action-to-flag table (plan 39 B5a): every flag of the
flat parser lives in one group, and each action owns the groups its handler
reads."""
import argparse
import shlex

from test_exp_parser_characterization import CORPUS
from vmn_exp.cli.exp_parser.actions import ACTION_FLAGS
from vmn_exp.cli.exp_parser.build import GROUPS, group_flags, owned_flags
from vmn_exp.cli.plugin import EXPERIMENT_ACTIONS, _add_experiment_parser


def _flat_parser():
    sub = argparse.ArgumentParser().add_subparsers(dest="command")
    _add_experiment_parser(sub, "experiment")
    return sub.choices["experiment"]


def _flat_flags():
    return {flag for action in _flat_parser()._actions for flag in action.option_strings
            if flag not in ("-h", "--help")}


def test_every_flag_of_the_flat_parser_belongs_to_exactly_one_group():
    seen = [flag for group in GROUPS for flag in group_flags(group)]
    assert len(seen) == len(set(seen))
    assert set(seen) == _flat_flags()


def test_every_action_has_a_flag_tuple():
    choices = next(a.choices for a in _flat_parser()._actions if a.dest == "action")
    assert list(ACTION_FLAGS) == list(choices) == EXPERIMENT_ACTIONS
    for action, groups in ACTION_FLAGS.items():
        assert isinstance(groups, tuple) and groups, action
        assert set(groups) <= set(GROUPS), action


def test_every_group_is_used_by_some_action():
    used = {group for groups in ACTION_FLAGS.values() for group in groups}
    assert used == set(GROUPS)


def _flags_of(argv):
    options = argv[:argv.index("--")] if "--" in argv else argv
    return {token.split("=", 1)[0] for token in options if token.startswith("-")}


def test_every_corpus_line_uses_only_flags_its_action_owns():
    for line, _ in CORPUS:
        argv = shlex.split(line)
        assert _flags_of(argv) <= owned_flags(argv[0]), line
