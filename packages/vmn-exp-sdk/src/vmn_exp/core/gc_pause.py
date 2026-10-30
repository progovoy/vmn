#!/usr/bin/env python3
"""Pause the cyclic garbage collector over a bulk load.

An index load or refresh at 100k records allocates tens of millions of
containers that all live on. Each collection the allocations trigger on the
way traverses every one of them again — most of a restart's ~4s record load
was the collector, not the decoding. Nothing in such a stretch makes cycles
worth collecting early, so :func:`gc_paused` turns collection off for it.

Process-wide state shared by threads: collection resumes once the last of the
overlapping pauses ends, and only if it was on when the first began — or as
:func:`set_automatic` last set it during the pauses.
"""
import gc
import threading
from contextlib import contextmanager

_LOCK = threading.Lock()
_depth = 0
_resume = False


@contextmanager
def gc_paused():
    global _depth, _resume
    with _LOCK:
        if _depth == 0:
            _resume = gc.isenabled()
            gc.disable()
        _depth += 1
    try:
        yield
    finally:
        with _LOCK:
            _depth -= 1
            if _depth == 0 and _resume:
                gc.enable()


def set_automatic(enabled):
    """Turn automatic collection on or off for good (see
    :mod:`~vmn_exp.core.gc_policy`); a pause running now ends into it."""
    global _resume
    with _LOCK:
        if _depth:
            _resume = enabled
        else:
            (gc.enable if enabled else gc.disable)()


def freeze_long_lived():
    """Move every object alive now out of the collected generations, after a
    full collection reclaims every unreachable cycle (it traverses only what
    is not frozen yet). For a long-lived server whose bulk data (a board's
    100k rows) would otherwise be traversed by each full collection; frozen
    objects are still freed by reference counting, but any cycle alive now
    outlives its use for good — so call it rarely (a board built from
    scratch), never per index generation."""
    gc.collect()
    gc.freeze()
