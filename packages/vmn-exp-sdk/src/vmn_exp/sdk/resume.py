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

from vmn_exp.core.fork import resolve_run
from vmn_exp.core.status import load_run_state, parse_iso
from vmn_exp.sdk import _resolve_app_name
from vmn_exp.sdk.create import (
    SNAPSHOT_METADATA_ENV,
    experiment_conf,
    gitmode,
    snapshot_app_names,
    snapshot_mode_storage,
)
from vmn_exp.sdk.ranks import as_int

RESUME_ENV = "VMN_RESUME_RUN_ID"


def requested_run_id(run_id):
    """The run to resume: *run_id*, else ``VMN_RESUME_RUN_ID``, else None.

    The env value is consumed: left in place, every run this process opens next
    — and every vmn subprocess it launches — would resume the same run again.
    """
    if run_id:
        return run_id
    return os.environ.pop(RESUME_ENV, None) or None


def locate(app_name, ref, storage, action="resume"):
    """``(app_name, storage, verstr, prior_state, exp_conf)``; ValueError if not
    found."""
    meta_path = os.environ.get(SNAPSHOT_METADATA_ENV)
    exp_conf = {}
    if meta_path:
        app_name = _resolve_app_name(app_name, lambda: snapshot_app_names(meta_path))
        storage = storage or snapshot_mode_storage()
    else:
        checkout = gitmode()
        app_name = _resolve_app_name(app_name, checkout.stamped_apps)
        vcs = checkout.build_vcs(app_name)
        exp_conf = experiment_conf(vcs)
        if storage is None:
            storage = checkout.build_storage(vcs)

    verstr = resolve_run(storage, app_name, ref, action)
    prior_state = load_run_state(storage, app_name, verstr) or {}
    return app_name, storage, verstr, prior_state, exp_conf


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
