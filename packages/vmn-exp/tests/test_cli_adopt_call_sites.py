"""Every ``_Supervision`` a run handler builds offers the run to its child
unless adoption is turned off (plan 38 A4)."""
import argparse

from empty_storage import EmptyStorage

from vmn_exp.cli.run import _Supervision, run_supervision
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
    sup = _Supervision(EmptyStorage(), "app", VERSTR, _args(), cwd="/work", adopt=adopt)
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
    sup = _Supervision(EmptyStorage(), "app", VERSTR, _args(), None, None, None, "/work")
    assert sup.adopt is False
