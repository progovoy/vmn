"""Every ``_Supervision`` a run handler builds offers the run to its child
unless adoption is turned off (plan 38 A4; rerun and sweep trials, A12)."""
import argparse
import threading
from types import SimpleNamespace

from empty_storage import EmptyStorage

from vmn_exp.cli.rerun import rerun_supervision
from vmn_exp.cli.run import _Supervision, run_supervision
from vmn_exp.cli.sweep.agent import trial_supervision
from vmn_exp.cli.supervised_env import ADOPT_PID_ENV, ADOPT_RUN_ID_ENV

VERSTR = "1.0.0-dev.abc.r1"


def _args(**over):
    return argparse.Namespace(capture_output=False, kill_grace_sec=1, **over)


def test_run_supervision_adopts_by_default():
    sup = run_supervision(EmptyStorage(), "app", VERSTR, _args(), None, "/repo", {})
    assert sup.adopt is True
    assert sup.root == "/repo"


def test_run_supervision_with_no_adopt_does_not():
    flag_off = run_supervision(
        EmptyStorage(), "app", VERSTR, _args(adopt_run=False), None, "/repo", {}
    )
    env_off = run_supervision(
        EmptyStorage(), "app", VERSTR, _args(), None, "/repo", {"VMN_EXP_ADOPT": "0"}
    )
    assert flag_off.adopt is False and env_off.adopt is False


def _supervision(adopt):
    sup = _Supervision(EmptyStorage(), "app", VERSTR, _args(), cwd="/work", adopt=adopt,
                       wait=threading.Event().wait)
    sup.metrics_path = "/tmp/metrics"
    sup.samples_tree = False
    return sup


def test_supervision_child_env_carries_the_token_only_when_adopting():
    adopting = _supervision(adopt=True)._child_env({}, 4242)
    assert adopting[ADOPT_RUN_ID_ENV] == VERSTR and adopting[ADOPT_PID_ENV] == "4242"

    plain = _supervision(adopt=False)._child_env({ADOPT_RUN_ID_ENV: "x"}, 4242)
    assert ADOPT_RUN_ID_ENV not in plain and ADOPT_PID_ENV not in plain
    assert plain["VMN_EXPERIMENT_ID"] == VERSTR


def test_supervision_does_not_adopt_unless_asked():
    sup = _Supervision(EmptyStorage(), "app", VERSTR, _args(), None, None, None, "/work",
                       wait=threading.Event().wait)
    assert sup.adopt is False


def _rerun_supervision(env, **over):
    source = SimpleNamespace(app_name="app", sweep_params={"lr": 0.1})
    workdir = SimpleNamespace(root="/ws", app_root="/ws/app")
    return rerun_supervision(EmptyStorage(), source, VERSTR,
                             _args(keep_worktree=True, **over), None, "/ws/app/sub",
                             workdir, "/repo/.vmn/exp", env)


def test_rerun_supervision_adopts_and_keeps_the_rerun_env():
    sup = _rerun_supervision({})
    assert sup.adopt is True
    assert sup.cwd == "/ws/app/sub" and sup.root == "/ws/app"
    assert sup.state_extra == {"workdir": "/ws"}
    assert sup.extra_env == {"VMN_WORKING_DIR": "/ws/app/sub", "VMN_RESUME_RUN_ID": None,
                             "VMN_EXPERIMENT_DIR": "/repo/.vmn/exp",
                             "VMN_SWEEP_PARAMS": '{"lr": 0.1}'}


def test_rerun_supervision_with_no_adopt_does_not():
    assert _rerun_supervision({}, adopt_run=False).adopt is False
    assert _rerun_supervision({"VMN_EXP_ADOPT": "off"}).adopt is False


def _trial_supervision(env):
    sweep_env = {"VMN_SWEEP_ID": "sw", "VMN_SWEEP_TRIAL": "3"}
    return trial_supervision(EmptyStorage(), "app", VERSTR, _args(), None, sweep_env,
                             print, "/repo", env)


def test_trial_supervision_adopts_and_keeps_the_sweep_env():
    sup = _trial_supervision({})
    assert sup.adopt is True
    assert sup.extra_env == {"VMN_SWEEP_ID": "sw", "VMN_SWEEP_TRIAL": "3"}
    assert sup.on_tick is print and sup.root == "/repo"


def test_trial_supervision_with_vmn_exp_adopt_0_does_not():
    assert _trial_supervision({"VMN_EXP_ADOPT": "0"}).adopt is False
