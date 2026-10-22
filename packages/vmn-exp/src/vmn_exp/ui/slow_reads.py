#!/usr/bin/env python3
"""Routes that read a run's records from the store run on their own threads.

FastAPI runs every sync route on anyio's default thread limiter (40). Run
detail, logs, series, patches and media read per-run objects — seconds to
minutes on S3, and a cancelled request keeps its thread — so they could fill
that pool and queue the cheap index-snapshot routes (list, facets, status)
behind them. :func:`slow_read` turns a sync route into one that runs on a
separate :data:`SLOW_READ_THREADS` limiter instead. A request whose client
has gone by the time a thread frees up (a hover prefetch, a page left before
it answered) is answered 499 without reading anything.
"""
import functools
import inspect
import math

from anyio import CapacityLimiter, to_thread
from anyio.lowlevel import RunVar
from fastapi import Request
from fastapi.responses import Response

from vmn_exp.ui.diag.requests import note_worker_start

SLOW_READ_THREADS = 24

# One limiter per event loop, like anyio's own default limiter.
_LIMITER = RunVar("vmn_ui_slow_read_limiter")
# The thread a seat of the limiter above runs on: the seat is the bound.
_UNBOUNDED = RunVar("vmn_ui_slow_read_threads")
_HIDDEN = "vmn_slow_read_request"
CLIENT_GONE = 499


def slow_read_limiter():
    """The running event loop's slow-read limiter."""
    try:
        return _LIMITER.get()
    except LookupError:
        limiter = CapacityLimiter(SLOW_READ_THREADS)
        _LIMITER.set(limiter)
        return limiter


def _threads():
    try:
        return _UNBOUNDED.get()
    except LookupError:
        limiter = CapacityLimiter(math.inf)
        _UNBOUNDED.set(limiter)
        return limiter


def _on_worker(route, *args, **kwargs):
    note_worker_start()
    return route(*args, **kwargs)


def _request_param(signature):
    """The name of *signature*'s Request parameter, else None."""
    return next((n for n, p in signature.parameters.items() if p.annotation is Request), None)


def _with_request(signature):
    """*signature* plus a keyword-only Request parameter FastAPI fills in."""
    hidden = inspect.Parameter(_HIDDEN, inspect.Parameter.KEYWORD_ONLY, annotation=Request)
    params = list(signature.parameters.values())
    return signature.replace(parameters=params + [hidden])


def slow_read(route):
    """*route* (a sync endpoint) as an async one run on the slow-read threads;
    FastAPI reads the parameters from *route*'s signature (plus the Request,
    to see a client that left while the read waited for a thread)."""
    signature = inspect.signature(route)
    own = _request_param(signature)

    @functools.wraps(route)
    async def run(*args, **kwargs):
        request = kwargs[own] if own else kwargs.pop(_HIDDEN)
        async with slow_read_limiter():
            if await request.is_disconnected():
                return Response(status_code=CLIENT_GONE)
            call = functools.partial(_on_worker, route, *args, **kwargs)
            return await to_thread.run_sync(call, limiter=_threads())

    run.__signature__ = signature if own else _with_request(signature)
    return run
