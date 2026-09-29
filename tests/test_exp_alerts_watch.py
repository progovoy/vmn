"""Status-transition alerts: a run that fails, or goes stuck, alerts once.

``failed`` is fired by the process that saw the run end (``vmn-exp run``'s
supervisor, the SDK's finish). ``stuck`` cannot be — the process is gone — so
``vmn-exp watch`` (cron-friendly) detects it. A per-run marker dedupes both.
"""
import datetime
import os

import yaml
from alert_helpers import WebhookReceiver, dead_url
from helpers import _PY, _bootstrap, _experiment, _storage, extract_dev_verstr

from vmn_exp.core.alerts import (
    ALERTS_FILE,
    Alerter,
    load_alert_config,
    watch_app,
)
from vmn_exp.core.status import RUN_STATE_FILE, load_run_state


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _create(app_layout, capfd):
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="create") == 0
    return extract_dev_verstr(capfd.readouterr().out)


def _age_run_state(app_layout, verstr, state):
    storage = _storage(app_layout)
    storage.save_file(
        app_layout.app_name, verstr, RUN_STATE_FILE, yaml.dump(state, sort_keys=False)
    )
    path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr,
        RUN_STATE_FILE,
    )
    old = (datetime.datetime.now() - datetime.timedelta(hours=1)).timestamp()
    os.utime(path, (old, old))


def _stuck_state(heartbeat):
    return {
        "state": "running", "command": ["train"], "pid": 4242, "host": "gpu-7",
        "started_at": heartbeat, "heartbeat": heartbeat, "heartbeat_seq": 3,
        "heartbeat_interval_sec": 30, "exit_code": None,
        "finished_at": None, "duration_sec": None,
    }


def _alerter(url, on):
    return Alerter(load_alert_config("app", exp_conf={"alerts": {
        "on": on, "sinks": [{"type": "webhook", "url": url}],
    }}))


def _an_hour_ago():
    return _iso(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1))


def test_stuck_run_alerts_once_per_transition(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _create(app_layout, capfd)
    _age_run_state(app_layout, verstr, _stuck_state(_an_hour_ago()))
    storage = _storage(app_layout)

    with WebhookReceiver() as hook:
        alerter = _alerter(hook.url, ["stuck"])
        fired = watch_app(storage, app_layout.app_name, alerter, within_sec=86400)
        assert fired == [(verstr, "stuck")]
        assert watch_app(storage, app_layout.app_name, alerter, within_sec=86400) == []

        # The run came back to life and got stuck again: a new transition.
        state = _stuck_state(_an_hour_ago())
        state["heartbeat_seq"] = 9
        state["heartbeat"] = _iso(
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30)
        )
        _age_run_state(app_layout, verstr, state)
        assert watch_app(storage, app_layout.app_name, alerter, within_sec=86400) == [
            (verstr, "stuck")
        ]

    assert len(hook.requests) == 2
    body = hook.bodies[0]
    assert body["trigger"] == "stuck"
    assert body["level"] == "warn"
    assert body["run_id"] == verstr
    assert body["host"] == "gpu-7"
    assert storage.load_file(app_layout.app_name, verstr, ALERTS_FILE)


def test_watch_skips_triggers_that_are_not_opted_in(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _create(app_layout, capfd)
    _age_run_state(app_layout, verstr, _stuck_state(_an_hour_ago()))
    with WebhookReceiver() as hook:
        alerter = _alerter(hook.url, ["failed"])
        assert watch_app(_storage(app_layout), app_layout.app_name, alerter, 86400) == []
    assert hook.requests == []


def test_watch_ignores_transitions_older_than_the_window(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _create(app_layout, capfd)
    _age_run_state(app_layout, verstr, _stuck_state("2020-01-01T00:00:00Z"))
    with WebhookReceiver() as hook:
        alerter = _alerter(hook.url, ["stuck"])
        assert watch_app(_storage(app_layout), app_layout.app_name, alerter, 86400) == []
    assert hook.requests == []


def test_undelivered_alert_is_retried_on_the_next_watch(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _create(app_layout, capfd)
    _age_run_state(app_layout, verstr, _stuck_state(_an_hour_ago()))
    storage = _storage(app_layout)

    assert watch_app(storage, app_layout.app_name, _alerter(dead_url(), ["stuck"]), 86400) == []
    with WebhookReceiver() as hook:
        fired = watch_app(storage, app_layout.app_name, _alerter(hook.url, ["stuck"]), 86400)
    assert fired == [(verstr, "stuck")]


def test_failing_child_of_vmn_exp_run_alerts_failed_once(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    with WebhookReceiver() as hook:
        monkeypatch.setenv("VMN_EXP_ALERT_WEBHOOK_URL", hook.url)
        monkeypatch.setenv("VMN_EXP_ALERT_ON", "failed")
        capfd.readouterr()
        code = _experiment(
            app_layout.app_name, action="run",
            run_cmd=[_PY, "-c", "import sys; sys.exit(3)"],
        )
        verstr = extract_dev_verstr(capfd.readouterr().out)
        assert code == 3
        assert hook.wait_for(1)

        # A later watch sees the marker and stays quiet.
        assert _experiment(app_layout.app_name, action="watch") == 0

    assert len(hook.requests) == 1
    body = hook.bodies[0]
    assert body["trigger"] == "failed"
    assert body["level"] == "error"
    assert body["run_id"] == verstr
    assert body["exit_code"] == 3


def test_succeeding_child_does_not_alert(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    with WebhookReceiver() as hook:
        monkeypatch.setenv("VMN_EXP_ALERT_WEBHOOK_URL", hook.url)
        monkeypatch.setenv("VMN_EXP_ALERT_ON", "failed,stuck")
        code = _experiment(app_layout.app_name, action="run", run_cmd=[_PY, "-c", "pass"])
        assert code == 0
    assert hook.requests == []


def test_unreachable_sink_does_not_change_the_runs_outcome(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv("VMN_EXP_ALERT_WEBHOOK_URL", dead_url())
    monkeypatch.setenv("VMN_EXP_ALERT_ON", "failed")
    capfd.readouterr()
    code = _experiment(
        app_layout.app_name, action="run", run_cmd=[_PY, "-c", "import sys; sys.exit(2)"],
    )
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert code == 2
    state = load_run_state(_storage(app_layout), app_layout.app_name, verstr)
    assert state["exit_code"] == 2


def test_watch_command_alerts_stuck_runs(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    verstr = _create(app_layout, capfd)
    _age_run_state(app_layout, verstr, _stuck_state(_an_hour_ago()))
    with WebhookReceiver() as hook:
        monkeypatch.setenv("VMN_EXP_ALERT_WEBHOOK_URL", hook.url)
        monkeypatch.setenv("VMN_EXP_ALERT_ON", "stuck")
        assert _experiment(app_layout.app_name, action="watch") == 0
        assert _experiment(app_layout.app_name, action="watch") == 0
    assert [b["run_id"] for b in hook.bodies] == [verstr]


def test_a_watch_tick_reads_only_the_candidates_markers(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    stuck = _create(app_layout, capfd)
    quiet = [_create(app_layout, capfd) for _ in range(3)]
    _age_run_state(app_layout, stuck, _stuck_state(_an_hour_ago()))
    for verstr in quiet:
        _age_run_state(app_layout, verstr, dict(
            _stuck_state(_an_hour_ago()), state="finished", exit_code=0,
            finished_at=_an_hour_ago(),
        ))
    storage = _storage(app_layout)
    with WebhookReceiver() as hook:
        alerter = _alerter(hook.url, ["stuck", "failed"])
        assert watch_app(storage, app_layout.app_name, alerter, 86400) == [(stuck, "stuck")]

        reads = []
        real_load_file, real_load_metadata = storage.load_file, storage.load_metadata
        monkeypatch.setattr(storage, "load_file", lambda app, v, name: (
            reads.append((v, name)) or real_load_file(app, v, name)))
        monkeypatch.setattr(storage, "load_metadata", lambda app, v: (
            reads.append((v, "metadata")) or real_load_metadata(app, v)))
        assert watch_app(storage, app_layout.app_name, alerter, 86400) == []
    assert reads == [(stuck, ALERTS_FILE)]
