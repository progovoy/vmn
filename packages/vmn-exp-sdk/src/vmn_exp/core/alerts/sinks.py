"""Where an alert goes: a sink is anything with ``send(alert)``.

A sink raises when delivery fails; the dispatcher (:mod:`.dispatch`) turns that
into a log line, so a sink can stay a few plain lines. Add a sink by writing a
class with ``send(alert, timeout)`` and registering a builder in
:data:`SINK_TYPES`.
"""
import json
import os
import subprocess
import urllib.request

DEFAULT_TIMEOUT_SEC = 5.0

_SLACK_COLORS = {"info": "#439fe0", "warn": "#daa038", "error": "#d00000"}


def _post_json(url, payload, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, default=str).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # urlopen raises HTTPError for any non-2xx status.
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


class WebhookSink:
    """POSTs the alert, as is, as JSON."""

    def __init__(self, url):
        self.url = url

    def send(self, alert, timeout=DEFAULT_TIMEOUT_SEC):
        _post_json(self.url, alert, timeout)


class SlackSink:
    """POSTs to a Slack incoming webhook in Slack's message format."""

    def __init__(self, url):
        self.url = url

    def send(self, alert, timeout=DEFAULT_TIMEOUT_SEC):
        _post_json(self.url, slack_payload(alert), timeout)


def slack_payload(alert):
    run = alert.get("run_name") or alert.get("run_id")
    headline = f"[{alert['level'].upper()}] *{alert['title']}* ({alert['app_name']} {run})"
    fields = [
        {"title": key.replace("_", " ").title(), "value": str(alert[key]), "short": True}
        for key in ("trigger", "status", "host", "exit_code")
        if alert.get(key) is not None
    ]
    return {
        "text": headline,
        "attachments": [{
            "color": _SLACK_COLORS.get(alert["level"], _SLACK_COLORS["info"]),
            "text": alert.get("text") or "",
            "fields": fields,
        }],
    }


class CommandSink:
    """Runs a shell command with the alert in ``VMN_ALERT_*`` env vars."""

    def __init__(self, command):
        self.command = command

    def send(self, alert, timeout=DEFAULT_TIMEOUT_SEC):
        env = dict(os.environ)
        env.update(alert_env(alert))
        subprocess.run(
            self.command, shell=True, env=env, timeout=timeout, check=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        )


def alert_env(alert):
    return {
        "VMN_ALERT_TRIGGER": alert["trigger"],
        "VMN_ALERT_TITLE": alert["title"],
        "VMN_ALERT_TEXT": alert.get("text") or "",
        "VMN_ALERT_LEVEL": alert["level"],
        "VMN_ALERT_APP": alert["app_name"] or "",
        "VMN_ALERT_RUN_ID": alert["run_id"] or "",
        "VMN_ALERT_STATUS": alert.get("status") or "",
        "VMN_ALERT_JSON": json.dumps(alert, default=str),
    }


SINK_TYPES = {
    "webhook": lambda spec: WebhookSink(spec["url"]),
    "slack": lambda spec: SlackSink(spec["url"]),
    "command": lambda spec: CommandSink(spec["command"]),
}


def build_sink(spec):
    """The sink a conf entry describes, or None for an unknown/incomplete one."""
    builder = SINK_TYPES.get((spec or {}).get("type"))
    try:
        return builder(spec) if builder else None
    except (KeyError, TypeError):
        return None
