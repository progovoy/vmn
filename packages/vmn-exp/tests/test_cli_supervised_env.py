"""The environment ``vmn-exp run`` hands its supervised child (plan 38 A4)."""
from vmn_exp.cli.supervised_env import ADOPT_PID_ENV, ADOPT_RUN_ID_ENV, supervised_env
from vmn_exp.sdk.sysmetrics import SUPERVISOR_SAMPLES_ENV


def _env(base=None, samples_tree=False, extra_env=None, adopt_pid=None):
    return supervised_env(
        base or {}, "1.0.0-dev.abc.r1", "app", "/tmp/metrics",
        samples_tree, extra_env or {}, adopt_pid,
    )


def test_exports_experiment_id_app_and_metrics_file():
    env = _env({"PATH": "/bin"})
    assert env["VMN_EXPERIMENT_ID"] == "1.0.0-dev.abc.r1"
    assert env["VMN_APP_NAME"] == "app"
    assert env["VMN_METRICS_FILE"] == "/tmp/metrics"
    assert env["PATH"] == "/bin"


def test_adds_the_adoption_run_id_and_pid_when_adopting():
    env = _env(adopt_pid=4242)
    assert env[ADOPT_RUN_ID_ENV] == "1.0.0-dev.abc.r1"
    assert env[ADOPT_PID_ENV] == "4242"
    assert env["VMN_EXPERIMENT_ID"] == "1.0.0-dev.abc.r1"


def test_no_adoption_vars_without_adopt_pid():
    env = _env()
    assert ADOPT_RUN_ID_ENV not in env and ADOPT_PID_ENV not in env


def test_inherited_adoption_vars_are_dropped_when_not_adopting():
    base = {ADOPT_RUN_ID_ENV: "launcher.r9", ADOPT_PID_ENV: "7"}
    env = _env(base)
    assert ADOPT_RUN_ID_ENV not in env and ADOPT_PID_ENV not in env
    assert base == {ADOPT_RUN_ID_ENV: "launcher.r9", ADOPT_PID_ENV: "7"}


def test_inherited_adoption_vars_are_replaced_when_adopting():
    env = _env({ADOPT_RUN_ID_ENV: "launcher.r9", ADOPT_PID_ENV: "7"}, adopt_pid=4242)
    assert env[ADOPT_RUN_ID_ENV] == "1.0.0-dev.abc.r1"
    assert env[ADOPT_PID_ENV] == "4242"


def test_extra_env_none_value_removes_a_variable():
    env = _env({"KEEP": "1", "DROP": "x"}, extra_env={"DROP": None, "ADD": "y"})
    assert "DROP" not in env
    assert env["KEEP"] == "1" and env["ADD"] == "y"


def test_supervisor_samples_marker_set_only_when_sampling():
    assert _env(samples_tree=True)[SUPERVISOR_SAMPLES_ENV] == "1"
    assert SUPERVISOR_SAMPLES_ENV not in _env(samples_tree=False)
