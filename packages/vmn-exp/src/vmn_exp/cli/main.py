"""The ``vmn-exp`` command: experiments, the model registry and the UI.

``vmn-exp create app`` / ``vmn-exp run app -- cmd`` run experiment actions;
``vmn-exp model ...``, ``vmn-exp sweep ...`` and ``vmn-exp ui`` reach the other commands;
``vmn-exp skill`` prints/installs the AI-agent skill block; ``vmn-exp login`` gets a server API token. It runs on vmn's CLI machinery (repo lock, app resolution)
through ``version_stamp.api``, with only its own commands registered.
"""
import sys

from version_stamp.api import VMN_ARGS, Frontend, vmn_run
from vmn_exp.cli.exp_parser.help import action_parser, help_action
from vmn_exp.cli.plugin import EXPERIMENT_ACTIONS, register_all
from vmn_exp.cli.version import display_version, installed_version
from vmn_exp.core.real_io import real_io

OWN_COMMANDS = ("exp", "experiment", "model", "report", "comment", "comments", "settings",
                "sweep", "ui")
ROOT_FLAGS = ("--debug",)
EPILOG = (
    f"A bare action runs as 'vmn-exp exp <action>': {', '.join(EXPERIMENT_ACTIONS)}. "
    "Also: 'vmn-exp skill' (the AI-agent skill block), 'vmn-exp migrate' "
    "(upgrade a store's layout), 'vmn-exp login' (a server API token), "
    "'vmn-exp buffers list|ship' (this host's kept log buffers)."
)


def _root_flag_count(argv):
    """How many leading tokens of *argv* are root flags such as ``--debug``."""
    count = 0
    while count < len(argv) and argv[count] in ROOT_FLAGS:
        count += 1
    return count


def _to_vmn_argv(argv):
    """``vmn-exp`` argv as vmn's parser reads it: bare actions go to ``exp``,
    also after leading root flags."""
    lead = _root_flag_count(argv)
    head, rest = list(argv[:lead]), list(argv[lead:])
    if rest and (rest[0] in OWN_COMMANDS or rest[0].startswith("-")):
        return head + rest
    return [*head, "exp", *rest]


def run_argv(argv, read_version, io):
    """``(exit code, container)`` for *argv*, as ``vmn_run`` returns them;
    ``--version`` prints what *read_version* gives. The commands vmn-exp runs
    itself get *io*; the ones vmn dispatches build theirs in cli/plugin.py."""
    if argv and argv[0] == "skill":
        from vmn_exp.cli.skill import run_skill

        return run_skill(argv[1:], io), None
    if argv and argv[0] == "migrate":
        from vmn_exp.cli.migrate import run_migrate

        return run_migrate(argv[1:], io), None
    if argv and argv[0] == "login":
        from vmn_exp.cli.login import run_login

        return run_login(argv[1:], io), None
    if argv and argv[0] == "buffers":
        from vmn_exp.cli.buffers_cmd import run_buffers

        return run_buffers(argv[1:], io), None
    register_all()
    command = argv[_root_flag_count(argv):][:1]
    if command and command[0] in VMN_ARGS and command[0] not in EXPERIMENT_ACTIONS:
        io.console.err(
            f"vmn-exp handles experiments, models and the UI; "
            f"run 'vmn {command[0]}' for that."
        )
        return 2, None
    vmn_argv = _to_vmn_argv(argv)
    action = help_action(vmn_argv)
    if action:
        action_parser(action).print_help()
        raise SystemExit(0)
    frontend = Frontend(prog="vmn-exp", version=display_version(read_version),
                        builtins=False, epilog=EPILOG)
    return vmn_run(vmn_argv, frontend=frontend)


def vmn_exp_run(argv, io):
    """``(exit code, container)`` for *argv*, with the installed vmn-exp version."""
    return run_argv(argv, installed_version, io)


def main(argv=None):
    code, _ = vmn_exp_run(list(sys.argv[1:] if argv is None else argv), real_io())
    return code
