"""The ``vmn-exp`` command: experiments, the model registry and the UI.

``vmn-exp create app`` / ``vmn-exp run app -- cmd`` run experiment actions;
``vmn-exp model ...``, ``vmn-exp sweep ...`` and ``vmn-exp ui`` reach the other commands;
``vmn-exp skill`` prints/installs the AI-agent skill block. It runs on vmn's CLI machinery (repo lock, app resolution)
through ``version_stamp.api``, with only its own commands registered.
"""
import sys

from version_stamp.api import VMN_ARGS, vmn_run
from vmn_exp.cli.plugin import EXPERIMENT_ACTIONS, register_all

OWN_COMMANDS = ("exp", "experiment", "model", "report", "comment", "comments", "sweep", "ui")


def _to_vmn_argv(argv):
    """``vmn-exp`` argv as vmn's parser reads it: bare actions go to ``exp``."""
    if argv and (argv[0] in OWN_COMMANDS or argv[0].startswith("-")):
        return list(argv)
    return ["exp", *argv]


def vmn_exp_run(argv):
    """``(exit code, container)`` for *argv*, as ``vmn_run`` returns them."""
    if argv and argv[0] == "skill":
        from vmn_exp.cli.skill import run_skill

        return run_skill(argv[1:]), None
    register_all()
    if argv and argv[0] in VMN_ARGS and argv[0] not in EXPERIMENT_ACTIONS:
        print(
            f"vmn-exp handles experiments, models and the UI; "
            f"run 'vmn {argv[0]}' for that.",
            file=sys.stderr,
        )
        return 2, None
    return vmn_run(_to_vmn_argv(argv))


def main(argv=None):
    code, _ = vmn_exp_run(list(sys.argv[1:] if argv is None else argv))
    return code
