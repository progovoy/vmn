#!/usr/bin/env python3
"""``vmn-exp run <app> -- cmd`` under ``VMN_MODE=disabled``: just run *cmd*.

No lock, auto-init, snapshot or run_state. vmn-exp replaces itself with the
command (``execvpe``), so its exit code and signals are its own. It still gets
``VMN_METRICS_FILE`` (``os.devnull``), so scripts that write to it keep working.
"""
import os
import sys

from version_stamp.api import VMN_LOGGER
from vmn_exp.cli.run import _child_cwd
from vmn_exp.sdk.mode import is_disabled

NOTICE = "vmn-exp: VMN_MODE=disabled - running the command without recording a run"


def exec_if_disabled(args):
    """Under ``VMN_MODE=disabled`` replace this process with ``args.run_cmd``
    (1 when there is no command); None otherwise, for the normal ``run``."""
    if not is_disabled():
        return None
    run_cmd = getattr(args, "run_cmd", None)
    if not run_cmd:
        VMN_LOGGER.error(
            "No command to run. Usage: vmn-exp run <app> -- <command> [args...]"
        )
        return 1
    print(NOTICE, file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    os.chdir(_child_cwd())
    os.execvpe(run_cmd[0], run_cmd, dict(os.environ, VMN_METRICS_FILE=os.devnull))
    return 0  # only reached when execvpe is stubbed out
