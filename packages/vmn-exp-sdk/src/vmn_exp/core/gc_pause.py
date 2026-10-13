#!/usr/bin/env python3
"""Pause the cyclic garbage collector over a bulk load.

An index load or refresh at 100k records allocates tens of millions of
containers that all live on. Each collection the allocations trigger on the
way traverses every one of them again — most of a restart's ~4s record load
was the collector, not the decoding. Nothing in such a stretch makes cycles
worth collecting early, so :func:`gc_paused` turns collection off for it.

Process-wide state shared by threads: collection resumes once the last of the
overlapping pauses ends, and only if it was on when the first began.
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
