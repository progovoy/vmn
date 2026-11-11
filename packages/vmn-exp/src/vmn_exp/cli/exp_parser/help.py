"""``vmn-exp <action> --help``: only the flags that action owns (plan 39 B5d).

Help only; parsing stays on the flat parser of :mod:`.build`.
"""
import argparse

from vmn_exp.cli.exp_parser.actions import ACTION_FLAGS, EXPERIMENT_ACTIONS
from vmn_exp.cli.exp_parser.build import GROUPS, add_positionals

EXPERIMENT_COMMANDS = ("exp", "experiment")
HELP_FLAGS = ("-h", "--help")


def help_action(vmn_argv):
    """The action whose own help *vmn_argv* asks for, else None.

    Only ``[--debug] exp|experiment <action> ...`` with ``-h``/``--help``
    before any ``--``; a flag before the action keeps the full help.
    """
    tokens = vmn_argv[1:] if vmn_argv[:1] == ["--debug"] else vmn_argv
    if len(tokens) < 2 or tokens[0] not in EXPERIMENT_COMMANDS:
        return None
    if tokens[1] not in EXPERIMENT_ACTIONS:
        return None
    own = tokens[:tokens.index("--")] if "--" in tokens else tokens
    return tokens[1] if any(token in HELP_FLAGS for token in own) else None


def action_parser(action):
    """A parser holding only *action*'s flags, built now: some help texts
    read a module value when the parser is built (``--max-bytes``)."""
    parser = argparse.ArgumentParser(prog=f"vmn-exp {action}")
    add_positionals(parser)
    for group, add_group in GROUPS.items():
        if group in ACTION_FLAGS[action]:
            add_group(parser)
    return parser
