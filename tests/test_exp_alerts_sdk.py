"""``run.alert()``: a W&B-style alert from inside the training loop.

It lands in the run's log as an ``alert`` entry, goes to every configured sink,
and repeats of one title are rate-limited so a loop cannot spam a channel.
"""
import pytest
from alert_helpers import WebhookReceiver, dead_url
from helpers import _bootstrap, _storage

from vmn_exp.sdk import start_run


def _alerts(app_layout, verstr):
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    return [e for e in log if e.get("type") == "alert"]


@pytest.fixture
def hook(monkeypatch):
    for var in ("VMN_EXP_ALERT_SLACK_URL", "VMN_EXP_ALERT_COMMAND"):
        monkeypatch.delenv(var, raising=False)
    with WebhookReceiver() as receiver:
        monkeypatch.setenv("VMN_EXP_ALERT_WEBHOOK_URL", receiver.url)
        monkeypatch.setenv("VMN_EXP_ALERT_ON", "alert,failed")
        yield receiver


def test_alert_is_logged_and_sent(app_layout, hook):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name, name="lr-sweep") as run:
        assert run.alert("loss exploded", text="nan at step 12", level="error") is True
        verstr = run.id
    assert hook.wait_for(1)

    entries = _alerts(app_layout, verstr)
    assert len(entries) == 1
    assert entries[0]["title"] == "loss exploded"
    assert entries[0]["text"] == "nan at step 12"
    assert entries[0]["level"] == "error"

    body = hook.bodies[0]
    assert body["trigger"] == "alert"
    assert body["run_id"] == verstr
    assert body["run_name"] == "lr-sweep"
    assert body["app_name"] == app_layout.app_name


def test_repeats_of_one_title_are_rate_limited(app_layout, hook):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        assert run.alert("slow epoch") is True
        assert run.alert("slow epoch") is False
        assert run.alert("other") is True
        assert run.alert("slow epoch", wait_sec=0) is True
        verstr = run.id
    assert hook.wait_for(3)
    assert [e["title"] for e in _alerts(app_layout, verstr)] == [
        "slow epoch", "other", "slow epoch",
    ]
    assert len(hook.requests) == 3


def test_invalid_level_raises(app_layout, hook):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        with pytest.raises(ValueError):
            run.alert("x", level="fatal")


def test_alert_without_sinks_is_still_logged(app_layout, monkeypatch):
    for var in ("VMN_EXP_ALERT_WEBHOOK_URL", "VMN_EXP_ALERT_SLACK_URL",
                "VMN_EXP_ALERT_COMMAND", "VMN_EXP_ALERT_ON"):
        monkeypatch.delenv(var, raising=False)
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        assert run.alert("heads up") is True
        verstr = run.id
    assert [e["title"] for e in _alerts(app_layout, verstr)] == ["heads up"]


def test_unreachable_sink_never_raises_into_the_run(app_layout, monkeypatch):
    monkeypatch.setenv("VMN_EXP_ALERT_WEBHOOK_URL", dead_url())
    monkeypatch.setenv("VMN_EXP_ALERT_ON", "alert,failed")
    _bootstrap(app_layout)
    run = start_run(app_layout.app_name)
    assert run.alert("x") is True
    run.finish(exit_code=1)


def test_failed_finish_alerts_failed(app_layout, hook):
    _bootstrap(app_layout)
    with pytest.raises(RuntimeError):
        with start_run(app_layout.app_name) as run:
            verstr = run.id
            raise RuntimeError("boom")
    assert hook.wait_for(1)
    body = hook.bodies[0]
    assert body["trigger"] == "failed"
    assert body["run_id"] == verstr
    assert body["exit_code"] == 1


def test_succeeded_finish_does_not_alert(app_layout, hook):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name):
        pass
    assert hook.requests == []


def test_failed_is_opt_in(app_layout, hook, monkeypatch):
    monkeypatch.setenv("VMN_EXP_ALERT_ON", "alert")
    _bootstrap(app_layout)
    run = start_run(app_layout.app_name)
    run.finish(exit_code=4)
    assert hook.requests == []


def test_secondary_rank_alert_is_a_no_op(hook):
    from vmn_exp.sdk.ranks import NoOpRun

    assert NoOpRun("app").alert("x", level="error") is None
    assert hook.requests == []


def test_exp_show_renders_an_alert_entry(app_layout, hook, capfd):
    from helpers import _experiment

    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        run.alert("loss exploded", text="nan at step 12", level="error")
        verstr = run.id
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=verstr) == 0
    assert "alert [error]: loss exploded: nan at step 12" in capfd.readouterr().out
