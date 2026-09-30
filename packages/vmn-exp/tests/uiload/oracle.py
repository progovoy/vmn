"""Expected run status from the harness event manifest.

Every writer appends JSONL lines ``{"t", "job_id", "event", "pid", ...}`` to its
own file under ``<run_dir>/events/``. Driver lines carry the *target* worker's
pid in ``pid`` (for ``spawned`` that is the spawned process).

Process-level events — ``stopping``, ``oom``, ``resumed``, ``signalled``,
``teardown`` — are keyed by pid: :func:`load_events` attaches each one to
every job whose ``started`` event has that pid, provided the job started at or
before the event and had not already ended (``finished``/``oom``). That is how
an inner job inherits its outer process's fate and how a reused pid is kept
apart from the dead process's jobs. A job's own events are always kept.

A ``killed`` job's worker may die without writing ``finished``: whoever reaps
the ``vmn-exp run`` process (the driver) must then write ``finished``
``{exit_code}`` for that job — until then the oracle stays ambiguous.

:func:`expected_status` returns ``None`` inside transition windows, where the
UI may legitimately show either side; callers must not assert then.
"""
import collections
import json
import pathlib

from vmn_exp.core.status import STALE_MULTIPLIER

PROCESS_EVENTS = frozenset({"stopping", "oom", "resumed", "signalled", "teardown"})
_FREEZE_EVENTS = ("stopping", "oom")  # heartbeat stops at this moment
_END_EVENTS = ("finished", "oom")


def load_events(run_dir):
    """Return ``{job_id: [events sorted by t]}`` from ``<run_dir>/events/*.jsonl``."""
    events = sorted(_read_all(pathlib.Path(run_dir) / "events"), key=lambda e: e["t"])
    by_job = collections.defaultdict(list)
    for event in events:
        by_job[event["job_id"]].append(event)
    jobs_by_pid = collections.defaultdict(list)
    for job_id, job_events in by_job.items():
        for event in job_events:
            if event["event"] == "started":
                jobs_by_pid[event["pid"]].append((event["t"], job_id))
    for event in events:
        if event["event"] in PROCESS_EVENTS:
            _attach(event, jobs_by_pid[event["pid"]], by_job)
    for job_events in by_job.values():
        job_events.sort(key=lambda e: e["t"])
    return dict(by_job)


def _attach(event, started_jobs, by_job):
    for start_t, job_id in started_jobs:
        if job_id == event["job_id"] or start_t > event["t"]:
            continue
        job_events = by_job[job_id]
        if any(e["event"] in _END_EVENTS and e["t"] <= event["t"] for e in job_events):
            continue
        job_events.append(event)


def _read_all(events_dir):
    for path in sorted(events_dir.glob("*.jsonl")):
        for line in path.read_text(errors="replace").splitlines():
            try:
                yield json.loads(line)
            except ValueError:
                continue  # a writer killed mid-line leaves a truncated tail


def expected_status(events, now, stale_sec, grace_sec=3.0):
    """Derive created/running/stuck/succeeded/failed, or None when ambiguous.

    ``events`` is one job's list from :func:`load_events` (process-level events
    already attached). Events after ``now`` are ignored. Ambiguous (None):
    before ``started`` or within ``grace_sec`` of it; within ``grace_sec`` of
    ``finished``; after ``signalled`` until ``finished``; after ``teardown``;
    while a frozen (stopped/oom) heartbeat is between surely-fresh and
    surely-stale; and for ``stale_sec / STALE_MULTIPLIER + grace_sec`` after ``resumed`` while
    the heartbeat refreshes. ``created`` is never expected: live jobs start
    running as soon as their run exists.
    """
    started_t = frozen_t = resumed_t = None
    signalled = False
    for event in events:
        if event["t"] > now:
            break
        name, t = event["event"], event["t"]
        if name == "finished":
            return _finished_status(event, now, grace_sec)
        if name == "teardown":
            return None
        if name == "started":
            started_t = t
        elif name in _FREEZE_EVENTS and frozen_t is None:
            frozen_t = t
        elif name == "resumed":
            frozen_t, resumed_t = None, t
        elif name == "signalled":
            signalled = True
    if started_t is None or signalled or now - started_t < grace_sec:
        return None
    max_heartbeat_gap = stale_sec / STALE_MULTIPLIER
    if frozen_t is not None:
        return _frozen_status(now - frozen_t, stale_sec, max_heartbeat_gap, grace_sec)
    if resumed_t is not None and now - resumed_t < max_heartbeat_gap + grace_sec:
        return None
    return "running"


def _finished_status(event, now, grace_sec):
    if now - event["t"] < grace_sec:
        return None
    return "succeeded" if event.get("exit_code") == 0 else "failed"


def _frozen_status(frozen_for, stale_sec, max_heartbeat_gap, grace_sec):
    """The last heartbeat landed within ``max_heartbeat_gap`` before freezing."""
    if frozen_for > stale_sec + grace_sec:
        return "stuck"
    if frozen_for < stale_sec - max_heartbeat_gap - grace_sec:
        return "running"
    return None


def expected_counts(events_by_job, now, stale_sec, grace_sec=3.0):
    """Return ``({status: n}, ambiguous_n)`` over every job."""
    counts, ambiguous = collections.Counter(), 0
    for events in events_by_job.values():
        status = expected_status(events, now, stale_sec, grace_sec)
        if status is None:
            ambiguous += 1
        else:
            counts[status] += 1
    return dict(counts), ambiguous
