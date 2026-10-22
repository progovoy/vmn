#!/usr/bin/env python3
"""The ``pools`` section: the thread limiters requests queue on.

anyio keeps its default limiter (sync routes, ``run_in_threadpool``) and the
slow-read one (:mod:`vmn_exp.ui.slow_reads`) per event loop, reachable only
from inside that loop. :func:`capture_limiters` (at startup and on each
``/diag`` request) records the serving loop's; the section reads those
references from any thread (a SIGUSR1 dump runs off the loop).
"""
from anyio import to_thread

_CAPTURED = {}  # name -> CapacityLimiter of the serving loop


def capture_limiters():
    """Record the running loop's limiters (call it on the event loop)."""
    from vmn_exp.ui.slow_reads import slow_read_limiter

    _CAPTURED["default"] = to_thread.current_default_thread_limiter()
    _CAPTURED["slow_read"] = slow_read_limiter()


def _stats(limiter):
    stats = limiter.statistics()
    return {"borrowed": stats.borrowed_tokens, "total": stats.total_tokens,
            "waiting": stats.tasks_waiting}


def pools_section():
    if not _CAPTURED:
        return {"note": "no event loop has served yet"}
    return {name: _stats(limiter) for name, limiter in list(_CAPTURED.items())}
