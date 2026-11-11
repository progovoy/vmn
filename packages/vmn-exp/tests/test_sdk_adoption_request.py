"""Who takes the run ``vmn-exp run`` offers its child (plan 38 A5): only the
supervisor's direct child, only a plain ``start_run()``, only once."""
from types import SimpleNamespace

from vmn_exp.cli import supervised_env
from vmn_exp.sdk.adoption import ADOPT_PID_ENV, ADOPT_RUN_ID_ENV, requested

V = "1.0.0-dev.abc.r1"
SUPERVISOR = 4242


def _env():
    return {ADOPT_RUN_ID_ENV: V, ADOPT_PID_ENV: str(SUPERVISOR), "OTHER": "x"}


def _parent_is(pid):
    return lambda: pid


def test_the_sdk_reads_the_names_the_supervisor_exports():
    assert (ADOPT_RUN_ID_ENV, ADOPT_PID_ENV) == (
        supervised_env.ADOPT_RUN_ID_ENV, supervised_env.ADOPT_PID_ENV)


def test_direct_child_gets_the_token_and_it_is_removed_from_env():
    env = _env()

    assert requested(env, _parent_is(SUPERVISOR)) == V
    assert env == {"OTHER": "x"}


def test_a_grandchild_is_refused_and_the_env_is_left_alone():
    env = _env()

    assert requested(env, _parent_is(SUPERVISOR + 1)) is None
    assert env == _env()


def test_no_adoption_with_explicit_parent():
    env = _env()
    assert requested(env, _parent_is(SUPERVISOR), parent="0.1.0-dev.x.r1") is None
    assert env == _env()


def test_no_adoption_with_nested():
    assert requested(_env(), _parent_is(SUPERVISOR), nested=True) is None


def test_no_adoption_with_fork_from():
    assert requested(_env(), _parent_is(SUPERVISOR), fork_from="r1") is None


def test_second_request_in_the_same_env_gets_none():
    env = _env()
    requested(env, _parent_is(SUPERVISOR))

    assert requested(env, _parent_is(SUPERVISOR)) is None


def test_no_token_is_no_adoption():
    assert requested({}, _parent_is(SUPERVISOR)) is None


def test_a_malformed_pid_is_refused_not_raised():
    env = dict(_env(), **{ADOPT_PID_ENV: "not-a-pid"})

    assert requested(env, _parent_is(SUPERVISOR)) is None


def test_refused_and_the_token_kept_while_a_run_is_open_on_this_thread():
    env = _env()

    assert requested(env, _parent_is(SUPERVISOR), active=SimpleNamespace(id="open")) is None
    assert env == _env()
