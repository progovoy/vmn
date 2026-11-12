"""The stuck floor, the run cadences, the local experiment dir, offline mode
and the alert config read the Env they are given (plan 44 G12 stage C)."""
import pytest

from fakes.env import FakeEnv
from vmn_exp.core import run_intervals, status, storage_resolve
from vmn_exp.core.alerts.config import load_alert_config


@pytest.fixture(autouse=True)
def _process_env_says_otherwise(monkeypatch):
    for name, value in {
        "VMN_EXP_MIN_STALE_SEC": "5", "VMN_EXP_HEARTBEAT_SEC": "7", "VMN_EXP_SYNC_SEC": "9",
        "VMN_EXPERIMENT_DIR": "/process/dir", "VMN_EXP_OFFLINE": "1",
        "VMN_EXP_ALERT_ON": "failed", "VMN_EXP_ALERT_COMMAND": "./process.sh",
    }.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("value, expected", [
    (None, status.MIN_STALE_SEC),
    ("8", 8.0),
    ("-1", status.MIN_STALE_SEC),
    ("nan", status.MIN_STALE_SEC),
    ("soon", status.MIN_STALE_SEC),
])
def test_min_stale_sec_from_the_given_env_and_default(value, expected):
    env = FakeEnv({} if value is None else {"VMN_EXP_MIN_STALE_SEC": value})

    assert status.min_stale_sec(env) == expected


def test_run_cadences_come_from_the_given_env_before_the_conf():
    env = FakeEnv({"VMN_EXP_HEARTBEAT_SEC": "3", "VMN_EXP_SYNC_SEC": "4"})
    conf = {"heartbeat_interval_sec": 11, "sync_interval_sec": 12}

    assert run_intervals.resolve_heartbeat_sec(None, env, conf) == 3
    assert run_intervals.resolve_sync_sec(None, env, conf) == 4
    assert run_intervals.resolve_heartbeat_sec(None, FakeEnv(), conf) == 11
    assert run_intervals.resolve_sync_sec(None, FakeEnv(), conf) == 12


def test_experiment_dir_falls_back_to_the_given_envs_dir():
    assert storage_resolve.experiment_dir(None, {}, FakeEnv({"VMN_EXPERIMENT_DIR": "/env/dir"})) == "/env/dir"
    assert storage_resolve.experiment_dir(None, {}, FakeEnv()) is None


def test_only_the_given_envs_offline_mode_drops_the_remote():
    params = {"store": "s3://b/root", "experiment_dir": "/d"}

    assert storage_resolve.drop_remote_if_offline(params, "/d", FakeEnv()) == params
    assert storage_resolve.drop_remote_if_offline(
        params, "/d", FakeEnv({"VMN_EXP_OFFLINE": "1"})) == {"experiment_dir": "/d"}


def test_alert_sinks_and_triggers_come_from_the_given_env():
    env = FakeEnv({"VMN_EXP_ALERT_ON": "stuck,alert", "VMN_EXP_ALERT_WEBHOOK_URL": "https://hook"})

    config = load_alert_config("app", exp_conf={}, env=env)
    bare = load_alert_config("app", exp_conf={}, env=FakeEnv())

    assert config.on == {"stuck", "alert"} and len(config.sinks) == 1
    assert bare.on == {"alert"} and bare.sinks == []
