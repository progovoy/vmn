"""Alert sinks, their configuration and the rate-limited dispatcher.

Every sink is best-effort: an unreachable endpoint or a failing hook command
must never raise into the run that fired the alert.
"""
import json
import os
import sys
import time

import pytest
from alert_helpers import WebhookReceiver, dead_url

from vmn_exp.core.alerts import (
    Alerter,
    CommandSink,
    SlackSink,
    WebhookSink,
    load_alert_config,
    make_alert,
)


def _alert(**overrides):
    fields = dict(
        trigger="alert", app_name="app", run_id="0.0.1-dev.1", title="loss exploded",
        text="loss=nan at step 12", level="error",
    )
    fields.update(overrides)
    return make_alert(**fields)


def test_make_alert_carries_run_identity_and_a_timestamp():
    alert = _alert(run_state={"host": "gpu-1", "exit_code": 3, "pid": 7})
    assert alert["trigger"] == "alert"
    assert alert["app_name"] == "app"
    assert alert["run_id"] == "0.0.1-dev.1"
    assert alert["title"] == "loss exploded"
    assert alert["level"] == "error"
    assert alert["host"] == "gpu-1"
    assert alert["exit_code"] == 3
    assert alert["timestamp"]


def test_make_alert_rejects_an_unknown_level():
    with pytest.raises(ValueError):
        _alert(level="fatal")


def test_webhook_sink_posts_the_alert_as_json():
    with WebhookReceiver() as hook:
        assert WebhookSink(hook.url).send(_alert()) is None
        assert hook.wait_for(1)
    path, headers, body = hook.requests[0]
    assert path == "/hook"
    assert headers["Content-Type"] == "application/json"
    assert body["title"] == "loss exploded"
    assert body["run_id"] == "0.0.1-dev.1"


def test_slack_sink_posts_a_slack_payload():
    with WebhookReceiver() as hook:
        SlackSink(hook.url).send(_alert())
        assert hook.wait_for(1)
    body = hook.bodies[0]
    assert "loss exploded" in body["text"]
    assert "app" in body["text"]
    attachment = body["attachments"][0]
    assert attachment["color"]
    assert "loss=nan" in attachment["text"]


def test_http_error_status_raises_from_the_sink_itself():
    with WebhookReceiver(status=500) as hook:
        with pytest.raises(Exception):
            WebhookSink(hook.url).send(_alert())


def test_command_sink_gets_the_alert_in_its_environment(tmp_path):
    out = tmp_path / "out.json"
    script = (
        "import json, os, sys; "
        "json.dump({k: v for k, v in os.environ.items() if k.startswith('VMN_ALERT_')}, "
        f"open({str(out)!r}, 'w'))"
    )
    CommandSink(f'"{sys.executable}" -c "{script}"').send(_alert())
    env = json.loads(out.read_text())
    assert env["VMN_ALERT_TITLE"] == "loss exploded"
    assert env["VMN_ALERT_TRIGGER"] == "alert"
    assert env["VMN_ALERT_LEVEL"] == "error"
    assert env["VMN_ALERT_APP"] == "app"
    assert env["VMN_ALERT_RUN_ID"] == "0.0.1-dev.1"
    assert json.loads(env["VMN_ALERT_JSON"])["text"] == "loss=nan at step 12"


def test_failing_command_raises_from_the_sink_itself():
    with pytest.raises(Exception):
        CommandSink("exit 3").send(_alert())


def test_config_from_conf_builds_sinks_and_triggers(monkeypatch):
    for var in ("VMN_EXP_ALERT_WEBHOOK_URL", "VMN_EXP_ALERT_SLACK_URL",
                "VMN_EXP_ALERT_COMMAND", "VMN_EXP_ALERT_ON"):
        monkeypatch.delenv(var, raising=False)
    conf = {"alerts": {
        "on": ["failed", "stuck"],
        "wait_sec": 5,
        "timeout_sec": 2,
        "sinks": [
            {"type": "webhook", "url": "http://example/a"},
            {"type": "slack", "url": "http://example/b"},
            {"type": "command", "command": "true"},
            {"type": "carrier-pigeon"},
        ],
    }}
    config = load_alert_config("app", exp_conf=conf)
    assert [type(s) for s in config.sinks] == [WebhookSink, SlackSink, CommandSink]
    assert config.on == {"failed", "stuck"}
    assert config.wait_sec == 5
    assert config.timeout_sec == 2


def test_env_vars_add_sinks_and_override_triggers(monkeypatch):
    monkeypatch.setenv("VMN_EXP_ALERT_WEBHOOK_URL", "http://example/a")
    monkeypatch.setenv("VMN_EXP_ALERT_SLACK_URL", "http://example/b")
    monkeypatch.setenv("VMN_EXP_ALERT_COMMAND", "true")
    monkeypatch.setenv("VMN_EXP_ALERT_ON", "failed, alert")
    config = load_alert_config("app", exp_conf={"alerts": {"on": ["stuck"]}})
    assert [type(s) for s in config.sinks] == [WebhookSink, SlackSink, CommandSink]
    assert config.on == {"failed", "alert"}


def test_only_explicit_alerts_fire_by_default(monkeypatch):
    monkeypatch.delenv("VMN_EXP_ALERT_ON", raising=False)
    config = load_alert_config("app", exp_conf={})
    assert config.on == {"alert"}


def test_config_reads_the_apps_conf_yml_from_the_root(tmp_path, monkeypatch):
    monkeypatch.delenv("VMN_EXP_ALERT_ON", raising=False)
    conf_dir = tmp_path / ".vmn" / "root" / "svc"
    conf_dir.mkdir(parents=True)
    (conf_dir / "conf.yml").write_text(
        "conf:\n  experiment:\n    alerts:\n      on: [stuck]\n"
        "      sinks:\n        - {type: webhook, url: 'http://example/a'}\n"
    )
    config = load_alert_config("root/svc", root=str(tmp_path))
    assert config.on == {"stuck"}
    assert len(config.sinks) == 1


def test_unreachable_sinks_never_raise_and_fail_fast(monkeypatch):
    monkeypatch.setenv("VMN_EXP_ALERT_WEBHOOK_URL", dead_url())
    monkeypatch.setenv("VMN_EXP_ALERT_SLACK_URL", dead_url())
    monkeypatch.setenv("VMN_EXP_ALERT_COMMAND", "exit 1")
    alerter = Alerter(load_alert_config("app", exp_conf={"alerts": {"timeout_sec": 2}}))
    start = time.monotonic()
    assert alerter.send(_alert()) is False
    assert time.monotonic() - start < 10


def test_one_working_sink_is_enough_for_a_delivery(monkeypatch):
    with WebhookReceiver() as hook:
        monkeypatch.setenv("VMN_EXP_ALERT_WEBHOOK_URL", hook.url)
        monkeypatch.setenv("VMN_EXP_ALERT_COMMAND", "exit 1")
        assert Alerter(load_alert_config("app", exp_conf={})).send(_alert()) is True
        assert hook.wait_for(1)


def test_admit_rate_limits_repeats_of_one_title():
    now = [100.0]
    alerter = Alerter(load_alert_config("app", exp_conf={"alerts": {"wait_sec": 60}}),
                      clock=lambda: now[0])
    assert alerter.admit("a") is True
    assert alerter.admit("a") is False
    assert alerter.admit("b") is True
    now[0] += 61
    assert alerter.admit("a") is True
    assert alerter.admit("a", wait_sec=0) is True


def test_wants_needs_the_trigger_and_a_sink(monkeypatch):
    for var in ("VMN_EXP_ALERT_WEBHOOK_URL", "VMN_EXP_ALERT_SLACK_URL",
                "VMN_EXP_ALERT_COMMAND", "VMN_EXP_ALERT_ON"):
        monkeypatch.delenv(var, raising=False)
    assert not Alerter(load_alert_config("app", exp_conf={})).wants("alert")
    monkeypatch.setenv("VMN_EXP_ALERT_WEBHOOK_URL", "http://example/a")
    alerter = Alerter(load_alert_config("app", exp_conf={}))
    assert alerter.wants("alert")
    assert not alerter.wants("failed")


def test_send_async_delivers_and_drain_waits(monkeypatch):
    with WebhookReceiver() as hook:
        monkeypatch.setenv("VMN_EXP_ALERT_WEBHOOK_URL", hook.url)
        alerter = Alerter(load_alert_config("app", exp_conf={}))
        alerter.send_async(_alert())
        alerter.drain(5)
        assert len(hook.requests) == 1


def test_config_never_raises_on_a_broken_conf_file(tmp_path, monkeypatch):
    monkeypatch.delenv("VMN_EXP_ALERT_ON", raising=False)
    conf_dir = tmp_path / ".vmn" / "app"
    conf_dir.mkdir(parents=True)
    (conf_dir / "conf.yml").write_text("conf: [unbalanced\n")
    config = load_alert_config("app", root=str(tmp_path))
    assert config.on == {"alert"}
    assert os.path.isdir(str(conf_dir))
