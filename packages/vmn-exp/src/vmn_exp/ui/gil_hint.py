#!/usr/bin/env python3
"""A one-time hint about the interpreter for a large store.

Request threads and the refresher share one core under the GIL; at 100k runs
that caps the ui at a few dozen requests per second. A free-threaded build
(3.14t) spreads them over every core. The ui only reads the store, so it can
run on its own interpreter, apart from the jobs' environment.

Past :data:`FREE_THREADED_MAX_RECORDS` runs the trade turns: a free-threaded
build allocates with mimalloc, whose per-thread heaps keep what a live worker
thread once allocated and another thread freed (measured: rebuilding a
structure freed that way doubles RSS; pymalloc reuses it), and each automatic
collection stops every thread to scan the whole heap. A 486k-run server grew
from 28 to 250 GiB with two-minute stalls on 3.14t, so there the hint points
the other way.
"""
import sys
import threading

from vmn_exp._base import ensure_logger

LARGE_STORE_RECORDS = 10_000
FREE_THREADED_MAX_RECORDS = 200_000
_DOCS = "(see docs/vmn-exp/ui.md, 'Large stores: run the UI on free-threaded Python')"
HINT = (
    "This store has %d runs and this Python has the GIL enabled, which caps the "
    "ui at one core. For a much faster ui, run it on a free-threaded Python:\n\n"
    "  uvx --python 3.14t --from 'vmn-exp[ui]' vmn-exp ui ...\n\n" + _DOCS
)
HUGE_HINT = (
    "This store has %d runs and this Python is free-threaded. At this size its "
    "allocator keeps every worker thread's peak memory and each automatic garbage "
    "collection stops the whole process for seconds to minutes; run the ui on a "
    "GIL build (e.g. uvx --python 3.14 ...) instead " + _DOCS
)


def gil_enabled():
    is_enabled = getattr(sys, "_is_gil_enabled", None)
    return True if is_enabled is None else is_enabled()


def _hint(records, gil):
    """The hint a store of *records* runs warrants on this interpreter, or None."""
    if records < LARGE_STORE_RECORDS:
        return None
    if records >= FREE_THREADED_MAX_RECORDS:
        return None if gil else HUGE_HINT
    return HINT if gil else None


class GilHint:
    def __init__(self, gil_enabled=gil_enabled):
        self._gil_enabled = gil_enabled
        self._given = False
        self._lock = threading.Lock()

    def note(self, records):
        """Log the hint the first time a store of *records* runs warrants it."""
        hint = _hint(records, self._gil_enabled())
        if hint is None:
            return
        with self._lock:
            if self._given:
                return
            self._given = True
        ensure_logger().warning(hint % records)
