"""Alerts on status transitions: a run went ``failed`` or ``stuck``.

Each run alerts once per transition: a delivered alert is recorded in the run's
``alerts_sent.yml`` (through the storage, so local and S3 alike), keyed by the
transition — a failed run by its ``finished_at``, a stuck one by its last
heartbeat, so a run that recovers and gets stuck again alerts again. An alert
no sink accepted is not recorded, and the next watch retries it.
"""
import datetime

import yaml

from vmn_exp._base import VMN_LOGGER, now_iso, yaml_safe_load
from vmn_exp.core import index as experiment_index
from vmn_exp.core.alerts.dispatch import make_alert
from vmn_exp.core.status import FAILED, STUCK, derive_status, parse_iso

ALERTS_FILE = "alerts_sent.yml"


def _now(now=None):
    return now or datetime.datetime.now(datetime.timezone.utc)


def load_sent(storage, app_name, verstr):
    """``{transition key: sent_at}`` for one run; {} when none (or unreadable)."""
    try:
        raw = storage.load_file(app_name, verstr, ALERTS_FILE)
        data = yaml_safe_load(raw) if raw else None
    except Exception:
        VMN_LOGGER.debug("Failed to load the alert markers", exc_info=True)
        return {}
    sent = (data or {}).get("sent") if isinstance(data, dict) else None
    return sent if isinstance(sent, dict) else {}


def save_sent(storage, app_name, verstr, sent):
    """Write the run's ``{transition key: sent_at}`` markers; returns the bytes."""
    data = yaml.dump({"sent": sent})
    storage.save_file(app_name, verstr, ALERTS_FILE, data)
    return data


def _mark_sent(storage, app_name, verstr, sent, key):
    save_sent(storage, app_name, verstr, dict(sent, **{key: now_iso()}))


def transition_key(status, run_state):
    if status == FAILED:
        return f"failed@{run_state.get('finished_at')}"
    return f"stuck@{run_state.get('heartbeat') or run_state.get('started_at')}"


def _transition_time(status, run_state):
    ts = run_state.get("finished_at") if status == FAILED else (
        run_state.get("heartbeat") or run_state.get("started_at")
    )
    return parse_iso(ts)


def transition_alert(app_name, verstr, run_state, status, run_name=None, now=None):
    if status == FAILED:
        title = f"Run {verstr} failed"
        text = f"exit code {run_state.get('exit_code')}"
        if run_state.get("signal"):
            text += f" ({run_state['signal']})"
        level = "error"
    else:
        title = f"Run {verstr} is stuck"
        since = _transition_time(status, run_state)
        age = int((_now(now) - since).total_seconds()) if since else None
        text = (
            f"no heartbeat for {age}s (host {run_state.get('host')}, "
            f"pid {run_state.get('pid')})"
        )
        level = "warn"
    return make_alert(
        status, app_name, verstr, title, text, level,
        run_name=run_name, status=status, run_state=run_state,
    )


def alert_transition(storage, app_name, verstr, run_state, status, alerter,
                     run_name=None, now=None):
    """Alert *status* for this run unless already sent; True if delivered now."""
    key = transition_key(status, run_state)
    sent = load_sent(storage, app_name, verstr)
    if key in sent:
        return False
    alert = transition_alert(app_name, verstr, run_state, status, run_name, now)
    if not alerter.send(alert):
        return False
    _mark_sent(storage, app_name, verstr, sent, key)
    return True


def alert_if_failed(storage, app_name, verstr, run_state, alerter, run_name=None):
    """The run just finished: alert when it failed and ``failed`` is opted in."""
    if not run_state or not alerter.wants(FAILED):
        return False
    if derive_status(run_state) != FAILED:
        return False
    return alert_transition(storage, app_name, verstr, run_state, FAILED, alerter, run_name)


def watch_app(storage, app_name, alerter, within_sec, now=None):
    """Alert every run of *app_name* that went failed/stuck in the last
    *within_sec* seconds and has not alerted it yet. ``[(verstr, status)]``.

    Statuses come from the app's index snapshot; only the candidates' alert
    markers are read."""
    wanted = {s for s in (FAILED, STUCK) if alerter.wants(s)}
    if not wanted:
        return []
    now = _now(now)
    snap = experiment_index.indexed_snapshot(storage, app_name, wait=True)
    fired = []
    for verstr, run_state, status in _candidates(snap, wanted, within_sec, now):
        name = (snap.row(verstr) or {}).get("name")
        try:
            sent = alert_transition(
                storage, app_name, verstr, run_state, status, alerter, name, now
            )
        except Exception:
            VMN_LOGGER.debug(f"Alert check of {verstr} failed", exc_info=True)
            continue
        if sent:
            fired.append((verstr, status))
    return fired


def _candidates(snap, wanted, within_sec, now):
    """``(verstr, run_state, status)`` of the runs that went *wanted* within
    the window."""
    for verstr, run_state in snap.run_states.items():
        if not run_state:
            continue
        observed_at = snap.run_state_observed_at.get(verstr)
        status = derive_status(run_state, now=now, observed_at=observed_at)
        if status not in wanted:
            continue
        since = _transition_time(status, run_state)
        if since is not None and (now - since).total_seconds() <= within_sec:
            yield verstr, run_state, status
