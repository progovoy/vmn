#!/usr/bin/env python3
"""``start_run(fork_from=...)`` and ``start_run(run_id=..., rewind_to_step=N)``.

A fork is a new run seeded with another run's history up to a step (see
:mod:`vmn_exp.core.fork`); a rewind reopens a run and appends a ``rewind``
marker that hides its history past a step (see :mod:`vmn_exp.core.rewind`).
"""
from vmn_exp.core.fork import next_step, rewind_run, seed_fork, split_fork_ref
from vmn_exp.core.writer import get_writer_id
from vmn_exp.sdk import resume


def check_modes(ref, fork_from, rewind_to_step):
    """Reject combinations that mean nothing."""
    if fork_from and ref:
        raise ValueError("fork_from starts a new run; it cannot be combined with run_id")
    if rewind_to_step is not None and not ref:
        raise ValueError("rewind_to_step rewinds an existing run: pass run_id too")


def locate_source(app_name, fork_from, fork_step, storage, env):
    """``(app_name, storage, source verstr, step)``, checked before anything is
    created; *env* is the Env :func:`~vmn_exp.sdk.resume.locate` reads."""
    ref, step = split_fork_ref(fork_from, fork_step)
    app_name, storage, source, _, _ = resume.locate(app_name, ref, storage, action="fork", env=env)
    return app_name, storage, source, step


def seed(storage, app_name, verstr, source, step, io):
    """Seed the new run as the writer of *io*'s env and host; returns the
    step it continues from."""
    writer = get_writer_id(io.env, io.host)
    return next_step(seed_fork(storage, app_name, verstr, source, step, writer=writer)["step"])


def rewind(storage, app_name, verstr, prior_state, step, now, io):
    """Hide *verstr*'s history past *step* (refused while it runs at *now*),
    as the writer of *io*'s env and host; returns the step it continues from."""
    rewind_run(storage, app_name, verstr, step, prior_state, now,
               writer=get_writer_id(io.env, io.host))
    return next_step(step)
