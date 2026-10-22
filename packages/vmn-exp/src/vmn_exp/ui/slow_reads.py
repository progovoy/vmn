#!/usr/bin/env python3
"""Routes that read a run's records from the store run on their own threads.

FastAPI runs every sync route on anyio's default thread limiter (40). Run
detail, logs, series, patches and media read per-run objects — seconds to
minutes on S3, and a cancelled request keeps its thread — so they could fill
that pool and queue the cheap index-snapshot routes (list, facets, status)
behind them. :func:`slow_read` turns a sync route into one that runs on a
separate :data:`SLOW_READ_THREADS` limiter instead.
"""
import functools

from anyio import CapacityLimiter, to_thread
from anyio.lowlevel import RunVar

from vmn_exp.ui.diag.requests import note_worker_start

SLOW_READ_THREADS = 24

# One limiter per event loop, like anyio's own default limiter.
_LIMITER = RunVar("vmn_ui_slow_read_limiter")


def slow_read_limiter():
    """The running event loop's slow-read limiter."""
    try:
        return _LIMITER.get()
    except LookupError:
        limiter = CapacityLimiter(SLOW_READ_THREADS)
        _LIMITER.set(limiter)
        return limiter


def _on_worker(route, *args, **kwargs):
    note_worker_start()
    return route(*args, **kwargs)


def slow_read(route):
    """*route* (a sync endpoint) as an async one run on the slow-read threads;
    FastAPI still reads the parameters from *route*'s signature."""

    @functools.wraps(route)
    async def run(*args, **kwargs):
        call = functools.partial(_on_worker, route, *args, **kwargs)
        return await to_thread.run_sync(call, limiter=slow_read_limiter())

    return run
