"""The heartbeat and sync cadences an image can set without code.

Precedence: explicit (``start_run`` kwarg, ``vmn-exp run --heartbeat-interval``
/ ``--sync-interval``) > ``VMN_EXP_HEARTBEAT_SEC`` / ``VMN_EXP_SYNC_SEC`` >
conf ``experiment.heartbeat_interval_sec`` / ``experiment.sync_interval_sec``
> 30. Invalid or non-positive env/conf values are skipped.
"""
import os

import pytest
import yaml
from exp_helpers import _PY, _bootstrap, _experiment, _storage, extract_dev_verstr

from vmn_exp.core.run_intervals import (
    HEARTBEAT_ENV,
    SYNC_ENV,
    resolve_heartbeat_sec,
    resolve_sync_sec,
)
from vmn_exp.core.status import load_run_state
from vmn_exp.sdk import start_run


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (HEARTBEAT_ENV, SYNC_ENV, "VMN_EXPERIMENT_ID", "VMN_RESUME_RUN_ID"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("resolve,env,key", [
    (resolve_heartbeat_sec, HEARTBEAT_ENV, "heartbeat_interval_sec"),
    (resolve_sync_sec, SYNC_ENV, "sync_interval_sec"),
])
class TestPrecedence:
    def test_defaults_to_30(self, resolve, env, key):
        assert resolve(None) == 30
        assert resolve(None, {}) == 30

    def test_conf_beats_the_default(self, resolve, env, key):
        assert resolve(None, {key: 120}) == 120

    def test_env_beats_conf(self, resolve, env, key, monkeypatch):
        monkeypatch.setenv(env, "300")
        assert resolve(None, {key: 120}) == 300

    def test_explicit_beats_env(self, resolve, env, key, monkeypatch):
        monkeypatch.setenv(env, "300")
        assert resolve(5, {key: 120}) == 5

    @pytest.mark.parametrize("bad", ["", "abc", "0", "-5", "nan", "inf"])
    def test_a_bad_env_value_is_skipped(self, resolve, env, key, bad, monkeypatch):
        monkeypatch.setenv(env, bad)
        assert resolve(None, {key: 120}) == 120

    @pytest.mark.parametrize("bad", [0, -1, "abc", True, None, float("nan")])
    def test_a_bad_conf_value_is_skipped(self, resolve, env, key, bad):
        assert resolve(None, {key: bad}) == 30

    def test_a_fractional_value_is_kept(self, resolve, env, key, monkeypatch):
        monkeypatch.setenv(env, "0.5")
        assert resolve(None) == 0.5


def test_heartbeat_zero_explicit_falls_through_like_before(monkeypatch):
    monkeypatch.setenv(HEARTBEAT_ENV, "90")
    assert resolve_heartbeat_sec(0) == 90


def test_explicit_zero_sync_still_means_finish_only(monkeypatch):
    monkeypatch.setenv(SYNC_ENV, "90")
    assert resolve_sync_sec(0) == 0


def _set_conf(app_layout, **values):
    conf_path = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml")
    with open(conf_path) as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("conf", {}).setdefault("experiment", {}).update(values)
    with open(conf_path, "w") as f:
        yaml.dump(data, f)


def test_start_run_takes_the_cadence_from_conf(app_layout):
    _bootstrap(app_layout)
    _set_conf(app_layout, heartbeat_interval_sec=120, sync_interval_sec=240)
    run = start_run(app_layout.app_name)
    try:
        assert run._state["heartbeat_interval_sec"] == 120
        assert run._sync_interval_sec == 240
    finally:
        run.finish()


def test_start_run_takes_the_heartbeat_from_the_env(app_layout, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv(HEARTBEAT_ENV, "77")
    monkeypatch.setenv(SYNC_ENV, "66")
    run = start_run(app_layout.app_name)
    try:
        assert run._state["heartbeat_interval_sec"] == 77
        assert run._sync_interval_sec == 66
    finally:
        run.finish()


def test_start_run_explicit_args_beat_the_env(app_layout, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv(HEARTBEAT_ENV, "77")
    monkeypatch.setenv(SYNC_ENV, "66")
    run = start_run(app_layout.app_name, heartbeat_interval_sec=5, sync_interval_sec=None)
    try:
        assert run._state["heartbeat_interval_sec"] == 5
        assert not run._sync_interval_sec
    finally:
        run.finish()


def test_exp_run_takes_the_heartbeat_from_the_env(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv(HEARTBEAT_ENV, "45")
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="run",
                       run_cmd=[_PY, "-c", "print('ok')"]) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    state = load_run_state(_storage(app_layout), app_layout.app_name, verstr)
    assert state["heartbeat_interval_sec"] == 45


def test_exp_run_takes_the_heartbeat_from_conf(app_layout, capfd):
    _bootstrap(app_layout)
    _set_conf(app_layout, heartbeat_interval_sec=120)
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="run",
                       run_cmd=[_PY, "-c", "print('ok')"]) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    state = load_run_state(_storage(app_layout), app_layout.app_name, verstr)
    assert state["heartbeat_interval_sec"] == 120


def test_exp_run_flag_beats_the_env(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv(HEARTBEAT_ENV, "45")
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="run",
                       run_cmd=[_PY, "-c", "print('ok')"],
                       extra_args=["--heartbeat-interval", "7"]) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    state = load_run_state(_storage(app_layout), app_layout.app_name, verstr)
    assert state["heartbeat_interval_sec"] == 7
