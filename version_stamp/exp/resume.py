#!/usr/bin/env python3
"""Reopening a run: ``start_run(run_id=...)`` and ``VMN_RESUME_RUN_ID``.

A preempted job that is requeued should continue the run it was — same verstr,
same log — rather than start a new one. The resumed run republishes itself as
running, heartbeats, and appends to the log (a new process writes its own log
segment, which readers merge). ``started_at`` is kept, so the run's duration
spans every attempt; ``resume_count`` says how many there were.
"""
import datetime
import os

from version_stamp.cli.snapshot import _resolve_verstr
from version_stamp.core.experiment_status import load_run_state, parse_iso
from version_stamp.exp import _resolve_app_name
from version_stamp.exp.coldstart import build_vcs
from version_stamp.exp.create import (
    SNAPSHOT_METADATA_ENV,
    build_storage,
    snapshot_app_names,
    snapshot_mode_storage,
    stamped_apps,
)
from version_stamp.exp.ranks import as_int

RESUME_ENV = "VMN_RESUME_RUN_ID"


def requested_run_id(run_id):
    """The run to resume: *run_id*, else ``VMN_RESUME_RUN_ID``, else None.

    The env value is consumed: left in place, every run this process opens next
    — and every vmn subprocess it launches — would resume the same run again.
    """
    if run_id:
        return run_id
    return os.environ.pop(RESUME_ENV, None) or None


def locate(app_name, ref, storage):
    """``(app_name, storage, verstr, prior_state)``; ValueError if not found."""
    meta_path = os.environ.get(SNAPSHOT_METADATA_ENV)
    if meta_path:
        app_name = _resolve_app_name(app_name, lambda: snapshot_app_names(meta_path))
        storage = storage or snapshot_mode_storage()
    else:
        app_name = _resolve_app_name(app_name, stamped_apps)
        if storage is None:
            storage = build_storage(build_vcs(app_name))

    verstr, err = _resolve_verstr(storage, app_name, ref, kind="experiment")
    # The resolver passes stamped (non-dev) versions through unchecked.
    if not err and not storage.exists(app_name, verstr):
        err = "no such experiment"
    if err:
        raise ValueError(f"Cannot resume run '{ref}' of '{app_name}': {err}")
    return app_name, storage, verstr, load_run_state(storage, app_name, verstr) or {}


def resumed_state(prior, fresh):
    """The state a resumed run publishes: *fresh*, continuing *prior*."""
    state = dict(fresh)
    state["started_at"] = prior.get("started_at") or fresh["started_at"]
    state["resumed_at"] = fresh["started_at"]
    state["resume_count"] = (as_int(prior.get("resume_count")) or 0) + 1
    state["heartbeat_seq"] = (as_int(prior.get("heartbeat_seq")) or 0) + 1
    return state


def elapsed_before(state):
    """Seconds between the run's first start and now (0 when unknown)."""
    started = parse_iso(state.get("started_at"))
    if started is None:
        return 0.0
    now = datetime.datetime.now(datetime.timezone.utc)
    return max(0.0, (now - started).total_seconds())
