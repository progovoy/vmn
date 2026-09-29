"""Which sinks alerts go to, and which triggers fire them.

From ``experiment.alerts`` in the app's conf.yml, plus env vars — a pod has no
conf.yml, so each ``VMN_EXP_ALERT_*`` URL/command adds a sink and
``VMN_EXP_ALERT_ON`` overrides the trigger list::

    experiment:
      alerts:
        on: [failed, stuck, alert]   # default: [alert]
        wait_sec: 60                 # rate limit for repeats of one title
        timeout_sec: 5               # per sink delivery
        sinks:
          - {type: webhook, url: https://example.com/hook}
          - {type: slack, url: https://hooks.slack.com/services/...}
          - {type: command, command: ./notify.sh}
"""
import os

from vmn_exp.core.alerts.sinks import DEFAULT_TIMEOUT_SEC, build_sink
from vmn_exp.core.app_conf import read_experiment_conf

TRIGGERS = ("alert", "failed", "stuck")
DEFAULT_ON = ("alert",)
DEFAULT_WAIT_SEC = 60.0

ON_ENV = "VMN_EXP_ALERT_ON"
ENV_SINKS = (
    ("VMN_EXP_ALERT_WEBHOOK_URL", "webhook", "url"),
    ("VMN_EXP_ALERT_SLACK_URL", "slack", "url"),
    ("VMN_EXP_ALERT_COMMAND", "command", "command"),
)


class AlertConfig:
    def __init__(self, sinks=(), on=DEFAULT_ON, wait_sec=DEFAULT_WAIT_SEC,
                 timeout_sec=DEFAULT_TIMEOUT_SEC):
        self.sinks = list(sinks)
        self.on = set(on)
        self.wait_sec = wait_sec
        self.timeout_sec = timeout_sec


def load_alert_config(app_name=None, exp_conf=None, root=None):
    """The alert config for *app_name*. Never raises.

    *exp_conf* is the app's ``experiment`` conf section when the caller has it
    (the CLI's ``vcs.experiment``); None reads it from ``<root>/.vmn/<app>/conf.yml``.
    """
    if exp_conf is None:
        exp_conf = read_experiment_conf(app_name, root)
    alerts = (exp_conf or {}).get("alerts") or {}
    specs = list(alerts.get("sinks") or []) + _env_sink_specs()
    return AlertConfig(
        sinks=[s for s in map(build_sink, specs) if s is not None],
        # YAML 1.1 reads a bare `on:` key as the boolean True.
        on=_triggers(alerts.get("on", alerts.get(True))),
        wait_sec=_number(alerts.get("wait_sec"), DEFAULT_WAIT_SEC),
        timeout_sec=_number(alerts.get("timeout_sec"), DEFAULT_TIMEOUT_SEC),
    )


def _env_sink_specs():
    return [
        {"type": kind, key: os.environ[var]}
        for var, kind, key in ENV_SINKS
        if os.environ.get(var)
    ]


def _triggers(conf_on):
    raw = os.environ.get(ON_ENV)
    names = raw.split(",") if raw is not None else conf_on
    if names is None:
        return set(DEFAULT_ON)
    if isinstance(names, str):
        names = [names]
    return {str(n).strip() for n in names if str(n).strip() in TRIGGERS}


def _number(value, default):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default

