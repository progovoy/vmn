#!/usr/bin/env python3
"""Forking a run: a new run that starts with another run's history up to a step.

The fork is an ordinary new run (its own snapshot of the current tree, its own
verstr); its ``metadata.yml`` records ``forked_from: {verstr, step}`` and its
log opens with the source's params up to and including that step, and its
metric stream with the source's points (blocks marked inherited), copied with
``"inherited": true`` and their original timestamps, so the fork's
own entries — from step + 1 on — always fold over them. A fork is not a child:
``parent``, ``kind`` and ``tree_status`` do not change.

Without a step the whole (rewind-filtered) history is copied and the fork point
is the source's last step.

A rewind (:func:`rewind_run`) is the in-place counterpart: it appends a
``rewind`` marker to an existing run (see :mod:`vmn_exp.core.rewind`).
"""
import operator

from vmn_exp.core.resolve_ref import _resolve_verstr
from vmn_exp.core.rewind import create_rewind_entry, entry_step
from vmn_exp.core.status import RUNNING, derive_status, run_state_observed_at
from vmn_exp.core.metric_entries import split_metric_entries
from vmn_exp.core.writer import append_entries_to_log, append_metric_entries

STEP_SUFFIX = "?_step="
INHERITABLE = ("metrics", "params", "create")


def split_fork_ref(ref, step=None):
    """``(ref, step)`` of W&B-style ``"<ref>?_step=N"``; an explicit *step* wins."""
    if STEP_SUFFIX in ref:
        ref, suffix = ref.split(STEP_SUFFIX, 1)
        if step is None:
            step = suffix
    if step is None:
        return ref, None
    try:
        return ref, int(step)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid fork step '{step}': expected an integer") from None


def resolve_run(storage, app_name, ref, action):
    """The verstr of an existing run *ref*; ValueError naming *action* if none."""
    verstr, err = _resolve_verstr(storage, app_name, ref, kind="experiment")
    # The resolver passes stamped (non-dev) versions through unchecked.
    if not err and not storage.exists(app_name, verstr):
        err = "no such experiment"
    if err:
        raise ValueError(f"Cannot {action} run '{ref}' of '{app_name}': {err}")
    return verstr


def _inherited(entry):
    if entry.get("type") == "create":
        if not entry.get("params"):
            return None
        entry = {"timestamp": entry.get("timestamp"), "type": "params",
                 "params": entry["params"]}
    return dict(entry, inherited=True)


def _past(own, step):
    return own is not None and own > step


def inherited_entries(log, step=None):
    """``(entries, fork step)``: what a fork of *log* at *step* starts with.

    Stepped metrics are kept up to *step*; entries without a step (params,
    step-less metrics) are kept when they come before the first entry past it.
    """
    cut = len(log) if step is None else next(
        (i for i, e in enumerate(log) if _past(entry_step(e), step)), len(log)
    )
    entries, steps = [], []
    for position, entry in enumerate(log):
        if not isinstance(entry, dict) or entry.get("type") not in INHERITABLE:
            continue
        own = entry_step(entry)
        if own is None and position >= cut:
            continue
        if step is not None and _past(own, step):
            continue
        copied = _inherited(entry)
        if copied is not None:
            entries.append(copied)
            if own is not None:
                steps.append(own)
    return entries, step if step is not None else (max(steps) if steps else None)


def seed_fork(storage, app_name, verstr, source, step=None):
    """Make the new run *verstr* a fork of *source*; returns ``forked_from``."""
    log = storage.load_merged_log(app_name, source)
    entries, step = inherited_entries(log, step)
    forked_from = {"verstr": source, "step": step}
    storage.update_metadata(app_name, verstr, {"forked_from": forked_from})
    metrics, others = split_metric_entries(entries)
    if metrics:  # blocks marked inherited (plan 12 §5.4)
        append_metric_entries(storage, app_name, verstr, metrics, inherited=True)
    if others:
        append_entries_to_log(storage, app_name, verstr, others)
    return forked_from


def next_step(step):
    """The first step a run continuing after *step* logs."""
    return 0 if step is None else step + 1


def _rewind_step(step):
    try:
        valid = not isinstance(step, bool) and operator.index(step) >= 0
    except TypeError:
        valid = False
    if not valid:
        raise ValueError(f"Invalid rewind step '{step}': expected an integer >= 0")
    return operator.index(step)


def rewind_run(storage, app_name, verstr, step, prior_state):
    """Hide *verstr*'s history past *step* (*prior_state*: its ``run_state``).

    Refused while the run is live elsewhere: its writer would keep logging
    steps the rewind is about to hide.
    """
    step = _rewind_step(step)
    observed = run_state_observed_at(storage, app_name, verstr)
    if prior_state and derive_status(prior_state, observed_at=observed) == RUNNING:
        raise RuntimeError(
            f"Run '{verstr}' is running (host {prior_state.get('host')}, pid "
            f"{prior_state.get('pid')}); finish it before rewinding it."
        )
    append_entries_to_log(storage, app_name, verstr, [create_rewind_entry(step)])
