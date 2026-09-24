#!/usr/bin/env python3
"""Derive the status of an experiment run from its ``run_state.yml``.

``vmn exp run`` writes a small run-state file at start, refreshes its
``heartbeat`` while the child is alive, and finalizes it with an exit code.
Everything here is a pure function of that file plus the current time (and,
when the reader has it, the storage's mtime of the file, which makes the rule
immune to writer/reader clock skew), so the CLI, the ui readers and the
frontend all agree on what a run's status is.

Status is *derived*, never stored: a run whose heartbeat went stale without a
terminal exit code is ``stuck`` — the runner died, was OOM-killed or lost its
node, and nothing was left behind to say so. Stale means both clocks agree:
the writer's heartbeat timestamp and, when known, the store's write time of
``run_state.yml`` (see :func:`derive_status`).
"""
import datetime

from version_stamp.core import utils as core_utils
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
        state = core_utils.yaml_safe_load(raw) if raw else None
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


def run_state_observed_at(storage, app_name, verstr):
    """When the *storage* last saw ``run_state.yml`` written, or None.

    That mtime is stamped by the store (the filesystem, S3's LastModified), not
    by the writer, so it is immune to the writer's clock being off. None when
    the storage keeps no per-file signatures, or the record has no run state.
    """
    record_files = getattr(storage, "record_files", None)
    try:
        files = record_files(app_name, verstr) if record_files else None
        mtime = (files or {}).get(RUN_STATE_FILE, (None, None))[1]
    except Exception:
        VMN_LOGGER.debug("Failed to read the run state mtime", exc_info=True)
        return None
    return observed_at_from_mtime(mtime)


def observed_at_by_verstr(storage, app_name, verstrs):
    """``{verstr: run_state_observed_at(...)}`` for a direct (unindexed) read."""
    return {v: run_state_observed_at(storage, app_name, v) for v in verstrs}


def observed_at_from_mtime(mtime):
    """A storage file signature's mtime as an aware UTC datetime, or None.

    Local stores report st_mtime_ns, S3 float seconds: no epoch in seconds
    reaches 1e11 before the year 5000.
    """
    if not isinstance(mtime, (int, float)) or isinstance(mtime, bool):
        return None
    seconds = mtime / 1e9 if mtime > 1e11 else mtime
    return datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)


def _writer_age_sec(run_state, now):
    """Seconds since the writer's own clock last stamped a beat, or None.

    Before the first beat lands, the start time stands in for it.
    """
    age = _age_sec(run_state.get("heartbeat"), now)
    if age is None and run_state.get("heartbeat") is None:
        age = _age_sec(run_state.get("started_at"), now)
    return age


def _liveness_age_sec(run_state, now, observed_at):
    """Seconds since the freshest proof that the run is alive, or None.

    Two clocks can prove it: the writer's heartbeat timestamp and — when
    *observed_at* is known — the store's write time of ``run_state.yml``. The
    fresher one wins, so a run is stale only once *both* are. A heartbeat
    dated in the future is the writer's clock running ahead and proves
    nothing the store's clock can check, so it is ignored then.
    """
    writer_age = _writer_age_sec(run_state, now)
    if observed_at is None:
        return writer_age
    store_age = (now - observed_at).total_seconds()
    if writer_age is None or writer_age < 0:
        return store_age
    return min(writer_age, store_age)


def derive_status(run_state, now=None, observed_at=None):
    """Status of one run: created / running / stuck / succeeded / failed.

    *observed_at* is the storage mtime of ``run_state.yml``
    (:func:`run_state_observed_at`); pass it when you have it. A run with no
    exit code is ``stuck`` only when its heartbeat timestamp *and* that store
    write time are both older than :func:`stale_after_sec`; without
    *observed_at* the heartbeat timestamp alone decides.
    """
    if not run_state:
        return CREATED

    exit_code = run_state.get("exit_code")
    if exit_code is not None:
        return SUCCEEDED if int(exit_code) == 0 else FAILED
    if run_state.get("state") != "running":
        return CREATED

    # No exit code: only the heartbeat can tell a live run from a dead one.
    age = _liveness_age_sec(run_state, _now(now), observed_at)
    if age is None:
        return STUCK
    return RUNNING if age <= stale_after_sec(run_state) else STUCK


def status_fields(run_state, now=None, observed_at=None):
    """The full status payload for one run, ready to serialize.

    ``duration_sec`` is the recorded duration once the run finished, and the
    elapsed wall time while it is still going.
    """
    now = _now(now)
    run_state = run_state or {}
    status = derive_status(run_state, now=now, observed_at=observed_at)

    duration = run_state.get("duration_sec")
    if duration is None and run_state.get("started_at"):
        end = parse_iso(run_state.get("finished_at")) or now
        started = parse_iso(run_state.get("started_at"))
        if started is not None:
            duration = round((end - started).total_seconds(), 3)

    if observed_at is not None:
        stale_sec = _liveness_age_sec(run_state, now, observed_at)
    else:
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
