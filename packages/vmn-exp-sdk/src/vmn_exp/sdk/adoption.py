"""Whether ``start_run()`` takes the run ``vmn-exp run`` offers its child.

``vmn-exp run`` exports ``VMN_EXP_ADOPT_RUN_ID`` (its run) and
``VMN_EXP_ADOPT_PID`` (itself) to the command it supervises. A plain
``start_run()`` in that command's own process — the supervisor's direct
child, never a process further down — records into that run instead of
opening a nested one. The names match the CLI's (``cli/supervised_env.py``).
Pure: the environment and the parent pid are given.
"""

ADOPT_RUN_ID_ENV = "VMN_EXP_ADOPT_RUN_ID"
ADOPT_PID_ENV = "VMN_EXP_ADOPT_PID"


def requested(env, getppid, parent=None, nested=False, fork_from=None, active=None):
    """The offered run's verstr, or None. Granted only to a call naming no
    *parent*, *nested* or *fork_from*, with no run *active* on its thread
    (``start_run``'s re-entry guard stays in force), in the process whose
    parent (``getppid()``) is the supervisor. Granting consumes the offer
    from *env*: this process's subprocesses and its later runs nest instead."""
    verstr = env.get(ADOPT_RUN_ID_ENV)
    if not verstr or parent or nested or fork_from or active is not None:
        return None
    if not _is_parent(env.get(ADOPT_PID_ENV), getppid):
        return None
    env.pop(ADOPT_RUN_ID_ENV, None)
    env.pop(ADOPT_PID_ENV, None)
    return verstr


def _is_parent(pid, getppid):
    try:
        return int(pid) == getppid()
    except (TypeError, ValueError):
        return False
