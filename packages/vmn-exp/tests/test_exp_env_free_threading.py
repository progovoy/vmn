"""env.yml records whether the run's Python is free-threaded and whether its GIL
is actually enabled (``python.free_threaded`` / ``python.gil_enabled``); the
metadata env summary carries both at its top level, so they are queryable."""
import sys
import sysconfig

import yaml


def _simulate(monkeypatch, gil_disabled_build, gil_enabled=None):
    """Make this interpreter look like the given build; *gil_enabled* None
    means a Python without ``sys._is_gil_enabled`` (< 3.13)."""
    from vmn_exp.core import env as experiment_env

    real = sysconfig.get_config_var

    def config_var(name):
        if name == "Py_GIL_DISABLED":
            return gil_disabled_build
        return real(name)

    monkeypatch.setattr(experiment_env.sysconfig, "get_config_var", config_var)
    if gil_enabled is None:
        monkeypatch.delattr(sys, "_is_gil_enabled", raising=False)
    else:
        monkeypatch.setattr(sys, "_is_gil_enabled", lambda: gil_enabled, raising=False)


def test_free_threaded_build_with_gil_disabled(monkeypatch):
    from vmn_exp.core.env import capture_env

    _simulate(monkeypatch, 1, gil_enabled=False)
    python = capture_env()["python"]
    assert python["free_threaded"] is True
    assert python["gil_enabled"] is False


def test_free_threaded_build_with_gil_re_enabled(monkeypatch):
    from vmn_exp.core.env import capture_env

    _simulate(monkeypatch, 1, gil_enabled=True)
    python = capture_env()["python"]
    assert python["free_threaded"] is True
    assert python["gil_enabled"] is True


def test_default_build(monkeypatch):
    from vmn_exp.core.env import capture_env

    _simulate(monkeypatch, 0, gil_enabled=True)
    python = capture_env()["python"]
    assert python["free_threaded"] is False
    assert python["gil_enabled"] is True


def test_python_without_is_gil_enabled_reports_gil_on(monkeypatch):
    from vmn_exp.core.env import capture_env

    _simulate(monkeypatch, None, gil_enabled=None)
    python = capture_env()["python"]
    assert python["free_threaded"] is False
    assert python["gil_enabled"] is True


def test_capture_env_safe_of_another_interpreter_reports_its_own_values(monkeypatch):
    """The child's values, not ours: our interpreter is made to look
    free-threaded with the GIL off, the real child is whatever sys.executable is."""
    from vmn_exp.core.env import capture_env_safe

    expected_free = sysconfig.get_config_var("Py_GIL_DISABLED") == 1
    is_enabled = getattr(sys, "_is_gil_enabled", None)
    expected_gil = is_enabled() if is_enabled else True
    _simulate(monkeypatch, 0 if expected_free else 1, gil_enabled=not expected_gil)

    python = capture_env_safe(sys.executable)["python"]
    assert python["free_threaded"] is expected_free
    assert python["gil_enabled"] is expected_gil


def test_summary_carries_both_and_they_are_queryable(monkeypatch):
    from vmn_exp.core.env import capture_env, env_summary
    from vmn_exp.core.query import filter_rows

    _simulate(monkeypatch, 1, gil_enabled=False)
    summary = env_summary(capture_env())
    assert summary["free_threaded"] is True
    assert summary["gil_enabled"] is False

    rows = [{"env": summary}, {"env": {"python": "3.12.1"}}]
    assert filter_rows(rows, "env.gil_enabled = false") == rows[:1]
    assert filter_rows(rows, "env.free_threaded = true") == rows[:1]


def test_summary_of_an_old_env_has_neither():
    from vmn_exp.core.env import env_summary

    summary = env_summary({"python": {"version": "3.12.1"}, "packages": {}})
    assert "free_threaded" not in summary
    assert "gil_enabled" not in summary


def test_sdk_run_writes_them_to_env_yml(app_layout, monkeypatch):
    from exp_helpers import _bootstrap, _storage
    from vmn_exp.sdk import start_run

    _simulate(monkeypatch, 1, gil_enabled=False)
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        verstr = run.id

    st = _storage(app_layout)
    env = yaml.safe_load(st.load_file(app_layout.app_name, verstr, "env.yml"))
    assert env["python"]["free_threaded"] is True
    assert env["python"]["gil_enabled"] is False
    meta, _ = st.load(app_layout.app_name, verstr)
    assert meta["env"]["gil_enabled"] is False
