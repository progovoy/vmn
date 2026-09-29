#!/usr/bin/env python3
"""``start_run(fork_from=...)`` and ``start_run(run_id=..., rewind_to_step=N)``.

A fork is a new run seeded with another run's history up to a step (see
:mod:`vmn_exp.core.fork`); a rewind reopens a run and appends a ``rewind``
marker that hides its history past a step (see :mod:`vmn_exp.core.rewind`).
"""
from vmn_exp.core.fork import next_step, seed_fork, split_fork_ref
from vmn_exp.core.rewind import create_rewind_entry
from vmn_exp.core.status import RUNNING, derive_status, run_state_observed_at
from vmn_exp.core.writer import append_entries_to_log
from vmn_exp.sdk import resume


def check_modes(ref, fork_from, rewind_to_step):
    """Reject combinations that mean nothing."""
    if fork_from and ref:
        raise ValueError("fork_from starts a new run; it cannot be combined with run_id")
    if rewind_to_step is not None and not ref:
        raise ValueError("rewind_to_step rewinds an existing run: pass run_id too")


def locate_source(app_name, fork_from, fork_step, storage):
    """``(app_name, storage, source verstr, step)``, checked before anything is created."""
    ref, step = split_fork_ref(fork_from, fork_step)
    app_name, storage, source, _ = resume.locate(app_name, ref, storage, action="fork")
    return app_name, storage, source, step


def seed(storage, app_name, verstr, source, step):
    """Seed the new run; returns the step it continues from."""
    return next_step(seed_fork(storage, app_name, verstr, source, step)["step"])


def rewind(storage, app_name, verstr, prior_state, step):
    """Hide *verstr*'s history past *step*; returns the step it continues from.

    Refused while the run is live elsewhere: its writer would keep logging
    steps the rewind is about to hide.
    """
    observed = run_state_observed_at(storage, app_name, verstr)
    if prior_state and derive_status(prior_state, observed_at=observed) == RUNNING:
        raise RuntimeError(
            f"Run '{verstr}' is running (host {prior_state.get('host')}, pid "
            f"{prior_state.get('pid')}); finish it before rewinding it."
        )
    append_entries_to_log(storage, app_name, verstr, [create_rewind_entry(step)])
    return next_step(int(step))
