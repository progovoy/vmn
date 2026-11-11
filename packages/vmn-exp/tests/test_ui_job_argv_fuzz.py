"""No ui request body field can reach an option its action never meant to set.

For every job action and every body field (and every list element, dict key
and dict value inside one), a hostile value either makes build_command refuse
the request or changes only the field's own dest of the parsed command line.
Parsing is vmn's own parser, in process.
"""
import argparse
import copy

import pytest

from version_stamp.cli import args as core_args
from version_stamp.cli.args import parse_user_commands
from vmn_exp.cli.plugin import _add_experiment_parser, register_all
from vmn_exp.ui.job_argv import ACTIONS, EMITTED, SWITCHES
from vmn_exp.ui.jobs import build_command

APP = "my_app"
V1 = "0.0.1-dev.abc.def"
HOSTILE = ["-x", "--attach=/etc/passwd", "--", "-v", "--note=x", "-1", "-1 x",
           ["-x"], {"a": 1}, 7, True]

# action -> benign bodies; each body field -> the parsed dest it may change.
BENIGN = {
    "stamp": [{"release_mode": "minor", "prerelease": "rc", "dry_run": True}],
    "release": [{"verstr": "1.0.0"}],
    "goto": [{"verstr": "1.0.0"}],
    "restore": [{"verstr": V1}],
    "prune": [{"keep": 5}, {"older_than": "30d"}],
    "exp_create": [{"note": "n", "metrics": {"loss": 0.1, "acc": "0.9"}}],
    "exp_add": [{"verstr": V1, "note": "n", "metrics": {"loss": 0.1}}],
    "note": [{"verstr": V1, "note": "n"}],
    "exp_tag": [{"verstr": V1, "set": {"k": "v"}, "remove": ["o"]}],
    "exp_rewind": [{"verstr": V1, "step": 3}],
    "exp_push": [{"verstrs": [V1]}],
    "exp_archive": [{"verstrs": [V1]}],
    "exp_unarchive": [{"verstrs": [V1]}],
}
DEST = {
    "release_mode": "release_mode", "prerelease": "pr", "dry_run": "dry",
    "keep": "keep", "older_than": "older_than", "note": "note",
    "metrics": "metrics", "remove": "remove", "step": "step", "set": "refs",
}
VERSTR_DEST = {"exp_tag": "refs", "exp_archive": "refs", "exp_unarchive": "refs"}


def _dest(action, field):
    if field in ("verstr", "verstrs"):
        return VERSTR_DEST.get(action, "version")
    return DEST[field]


def _parse(argv):
    register_all()
    return vars(parse_user_commands(argv[1:]))


def _variants(value):
    """*value* replaced by each hostile value, then each element/key/value inside it."""
    for hostile in HOSTILE:
        yield hostile
    if isinstance(value, list):
        for i in range(len(value)):
            for inner in _variants(value[i]):
                yield value[:i] + [inner] + value[i + 1:]
    if isinstance(value, dict):
        for key in value:
            for hostile in HOSTILE:
                if not isinstance(hostile, (list, dict)):
                    yield {(hostile if k == key else k): v for k, v in value.items()}
            for inner in _variants(value[key]):
                yield dict(value, **{key: inner})


def _cases():
    for action, bodies in BENIGN.items():
        for body in bodies:
            for field, value in body.items():
                for variant in _variants(value):
                    yield action, body, field, variant


def _is_exp(argv):
    return argv[0] == "vmn-exp"


@pytest.mark.parametrize("action,body,field,variant", list(_cases()))
def test_no_body_field_can_set_another_dest(action, body, field, variant):
    benign_argv, err = build_command(action, APP, copy.deepcopy(body))
    assert err is None, err
    benign = _parse(benign_argv)
    command, err = build_command(action, APP, dict(copy.deepcopy(body), **{field: variant}))
    if err:
        assert command is None
        return
    parsed = _parse(command)
    changed = {k for k in benign.keys() | parsed.keys() if benign.get(k) != parsed.get(k)}
    assert changed <= {_dest(action, field)}, (command, changed)


@pytest.mark.parametrize("action", ACTIONS)
def test_benign_bodies_parse_to_the_intended_command(action):
    for body in BENIGN[action]:
        argv, err = build_command(action, APP, body)
        assert err is None, err
        parsed = _parse(argv)
        assert parsed["name"] == APP
        if _is_exp(argv):
            assert (parsed["command"], parsed["action"]) == ("experiment", argv[2])
        else:
            assert parsed["command"] == argv[1]


def test_every_action_is_fuzzed():
    assert set(BENIGN) == set(ACTIONS)


@pytest.mark.parametrize("action", [a for a in ACTIONS if a not in ("stamp", "release", "goto")])
def test_exp_actions_put_the_app_before_every_option(action):
    for body in BENIGN[action]:
        argv, _ = build_command(action, APP, body)
        assert argv[:2] == ["vmn-exp", "experiment"] and argv[3] == APP
        first_option = next((i for i, t in enumerate(argv) if t.startswith("-")), len(argv))
        assert all(t.startswith("-") for t in argv[first_option:]), argv


def _subcommand_words(argv):
    return 3 if _is_exp(argv) else 2


@pytest.mark.parametrize("action", ACTIONS)
def test_every_emitted_option_is_one_token_with_an_equals_sign(action):
    for body in BENIGN[action]:
        argv, _ = build_command(action, APP, body)
        for token in argv[_subcommand_words(argv):]:
            if token.startswith("-"):
                assert token in SWITCHES or token.split("=", 1)[0] in EMITTED[action], token
                assert token in SWITCHES or "=" in token, token


def _subparsers():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    for add in (core_args.add_arg_stamp, core_args.add_arg_release, core_args.add_arg_goto):
        add(sub)
    _add_experiment_parser(sub, "experiment")
    return sub.choices


@pytest.mark.parametrize("action", ACTIONS)
def test_every_emitted_flag_is_a_long_option_of_its_parser(action):
    argv, _ = build_command(action, APP, BENIGN[action][0])
    options = _subparsers()[argv[1]]._option_string_actions
    for flag in EMITTED[action]:
        assert flag.startswith("--") and flag in options, flag
