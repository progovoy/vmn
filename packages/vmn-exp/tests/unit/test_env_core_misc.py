"""The env capture, the capture opt-outs, the output cap and the command
sink read the Env they are given; index workers inherit the real one
(plan 44 G12)."""
import pytest

from fakes.env import FakeEnv
from vmn_exp.core import env as core_env
from vmn_exp.core import index_workers, output_log
from vmn_exp.core.alerts.config import load_alert_config


@pytest.fixture(autouse=True)
def _process_env_says_otherwise(monkeypatch):
    for name, value in {"VMN_IMAGE_DIGEST": "sha256:process", "VMN_CAPTURE_ENV": "0",
                        "VMN_EXP_OUTPUT_CAP_MB": "3", "PROCESS_ONLY": "1"}.items():
        monkeypatch.setenv(name, value)


def test_container_digest_comes_from_the_given_env():
    info = core_env._container_info(FakeEnv({"IMAGE_DIGEST": "sha256:given"}))

    assert info["image_digest"] == "sha256:given"
    assert "image_digest" not in (core_env._container_info(FakeEnv()) or {})


def test_a_captured_env_records_the_given_envs_image_digest():
    captured = core_env.capture_env_safe(FakeEnv({"IMAGE_DIGEST": "sha256:given"}))

    assert captured["container"]["image_digest"] == "sha256:given"


def test_capture_opt_out_reads_the_given_env():
    assert core_env.should_capture(None, {}, env=FakeEnv()) is True
    assert core_env.should_capture(None, {}, env=FakeEnv({"VMN_CAPTURE_ENV": "off"})) is False
    assert core_env.opted_in(True, "X_OFF", "k", {}, env=FakeEnv({"X_OFF": "no"})) is False


def test_output_cap_falls_back_to_the_given_env():
    given = FakeEnv({output_log.OUTPUT_CAP_ENV: "2"})

    assert output_log.output_cap_bytes(None, given) == 2 * 1024 * 1024
    assert output_log.output_cap_bytes(None, FakeEnv()) == output_log.DEFAULT_OUTPUT_CAP_MB * 1024 * 1024
    assert output_log.output_cap_bytes(1, given) == 1024 * 1024


def test_a_command_sink_runs_its_command_in_the_alert_configs_env():
    env = FakeEnv({"VMN_EXP_ALERT_COMMAND": "./notify.sh", "GIVEN_ONLY": "yes"})
    (sink,) = load_alert_config("app", exp_conf={}, env=env).sinks
    alert = {"trigger": "alert", "title": "t", "level": "info", "app_name": "app", "run_id": "r"}

    child_env = sink.child_env(alert)

    assert child_env["GIVEN_ONLY"] == "yes" and child_env["VMN_ALERT_TITLE"] == "t"
    assert "PROCESS_ONLY" not in child_env


def test_an_index_worker_inherits_the_real_environment(monkeypatch):
    spawned = []

    def spawn(cmd, env):
        spawned.append(env)
        raise OSError("no worker here")

    monkeypatch.setattr(index_workers, "_spawn", spawn)

    assert index_workers.run_in_worker(["python"], "payload") is None
    assert spawned == [None]
