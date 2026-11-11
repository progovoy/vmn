"""The environment ``vmn-exp run`` hands its supervised child.

Besides the run's id, app and metrics file, a supervisor that adopts offers
its run to its direct child: ``VMN_EXP_ADOPT_RUN_ID`` names the run and
``VMN_EXP_ADOPT_PID`` the supervisor, so only a process whose parent is that
pid takes it. ``--no-adopt`` or ``VMN_EXP_ADOPT=0`` turn the offer off.
Unrelated to :mod:`vmn_exp.core.adopt` (stream inheritance after a copy).
"""

ADOPT_RUN_ID_ENV = "VMN_EXP_ADOPT_RUN_ID"
ADOPT_PID_ENV = "VMN_EXP_ADOPT_PID"
ADOPT_SWITCH_ENV = "VMN_EXP_ADOPT"

_OFF_VALUES = ("0", "false", "no", "off")


def adopt_requested(args, env):
    """True unless ``--no-adopt`` was given or ``VMN_EXP_ADOPT`` turns it off."""
    if getattr(args, "adopt_run", True) is False:
        return False
    return env.get(ADOPT_SWITCH_ENV, "").strip().lower() not in _OFF_VALUES


def supervised_env(base_env, verstr, app_name, metrics_path, samples_tree,
                   extra_env, adopt_pid):
    """The child's env: *base_env* plus the run's variables, *extra_env* last
    (a None value removes the variable). An adoption token inherited from
    *base_env* is never passed on; the run's own is set when *adopt_pid* is."""
    from vmn_exp.sdk.sysmetrics import SUPERVISOR_SAMPLES_ENV  # exp's __init__ imports the CLI

    env = {k: v for k, v in base_env.items() if k not in (ADOPT_RUN_ID_ENV, ADOPT_PID_ENV)}
    env["VMN_EXPERIMENT_ID"] = verstr
    env["VMN_APP_NAME"] = app_name or ""
    env["VMN_METRICS_FILE"] = metrics_path
    if samples_tree:
        # An SDK run in the child must not sample the tree a second time.
        env[SUPERVISOR_SAMPLES_ENV] = "1"
    if adopt_pid is not None:
        env[ADOPT_RUN_ID_ENV] = verstr
        env[ADOPT_PID_ENV] = str(adopt_pid)
    env.update(extra_env)
    return {k: v for k, v in env.items() if v is not None}
