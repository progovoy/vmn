#!/usr/bin/env python3
"""Derive the status of an experiment run from its ``run_state.yml``.

``vmn exp run`` writes a small run-state file at start, refreshes its
``heartbeat`` while the child is alive, and finalizes it with an exit code.
Everything here is a pure function of that file plus the current time, so the
CLI, the ui readers and the frontend all agree on what a run's status is.

Status is *derived*, never stored: a run whose heartbeat went stale without a
terminal exit code is ``stuck`` — the runner died, was OOM-killed or lost its
node, and nothing was left behind to say so.
"""
import datetime

import yaml

from version_stamp.core.logging import VMN_LOGGER

CREATED = "created"  # experiment exists, no run was ever started
RUNNING = "running"  # heartbeat is fresh
STUCK = "stuck"  # claims running, heartbeat went stale
SUCCEEDED = "succeeded"  # finished, exit code 0
FAILED = "failed"  # finished, non-zero exit code

DEFAULT_HEARTBEAT_INTERVAL_SEC = 30
# A heartbeat may be late without the run being dead: a busy box, a slow S3
# PUT. Allow several missed beats, and never less than a minute.
STALE_MULTIPLIER = 3
MIN_STALE_SEC = 60

RUN_STATE_FILE = "run_state.yml"


def load_run_state(storage, app_name, verstr):
    """Return the run state of an experiment, or None when there is none.

    Never raises: an experiment that was created but never run has no run
    state, and a half-written file is no better than a missing one.
    """
    try:
        raw = storage.load_file(app_name, verstr, RUN_STATE_FILE)
        state = yaml.safe_load(raw) if raw else None
    except Exception:
        VMN_LOGGER.debug("Failed to load run state", exc_info=True)
        return None
    return state if isinstance(state, dict) else None


def parse_iso(ts):
    """Parse an ISO-8601 timestamp (``Z`` suffix included), or None."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _now(now=None):
    return now or datetime.datetime.now(datetime.timezone.utc)


def _age_sec(ts, now):
    parsed = parse_iso(ts)
    if parsed is None:
        return None
    return (now - parsed).total_seconds()


def heartbeat_interval_sec(run_state):
    """The run's heartbeat cadence, falling back to the default."""
    interval = (run_state or {}).get("heartbeat_interval_sec")
    try:
        return float(interval)
    except (TypeError, ValueError):
        return DEFAULT_HEARTBEAT_INTERVAL_SEC


def stale_after_sec(run_state):
    """How long a heartbeat may go unrefreshed before the run counts as stuck."""
    return max(heartbeat_interval_sec(run_state) * STALE_MULTIPLIER, MIN_STALE_SEC)


def derive_status(run_state, now=None):
    """Status of one run: created / running / stuck / succeeded / failed."""
    if not run_state:
        return CREATED

    exit_code = run_state.get("exit_code")
    if exit_code is not None:
        return SUCCEEDED if int(exit_code) == 0 else FAILED
    if run_state.get("state") != "running":
        return CREATED

    # No exit code: only the heartbeat can tell a live run from a dead one.
    # Before the first beat lands, the start time stands in for it.
    now = _now(now)
    age = _age_sec(run_state.get("heartbeat"), now)
    if age is None and run_state.get("heartbeat") is None:
        age = _age_sec(run_state.get("started_at"), now)
    if age is None:
        return STUCK
    return RUNNING if age <= stale_after_sec(run_state) else STUCK


def status_fields(run_state, now=None):
    """The full status payload for one run, ready to serialize.

    ``duration_sec`` is the recorded duration once the run finished, and the
    elapsed wall time while it is still going.
    """
    now = _now(now)
    run_state = run_state or {}
    status = derive_status(run_state, now=now)

    duration = run_state.get("duration_sec")
    if duration is None and run_state.get("started_at"):
        end = parse_iso(run_state.get("finished_at")) or now
        started = parse_iso(run_state.get("started_at"))
        if started is not None:
            duration = round((end - started).total_seconds(), 3)

    stale_sec = _age_sec(run_state.get("heartbeat"), now)
    return {
        "status": status,
        "exit_code": run_state.get("exit_code"),
        "started_at": run_state.get("started_at"),
        "finished_at": run_state.get("finished_at"),
        "heartbeat": run_state.get("heartbeat"),
        "duration_sec": duration,
        "pid": run_state.get("pid"),
        "host": run_state.get("host"),
        "command": run_state.get("command"),
        "stale_sec": None if stale_sec is None else round(stale_sec, 3),
        # The dashboard sizes its poll interval from this: there is no point
        # asking for a status more often than the run can publish one.
        "heartbeat_interval_sec": heartbeat_interval_sec(run_state),
    }
