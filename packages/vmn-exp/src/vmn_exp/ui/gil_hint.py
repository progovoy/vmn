#!/usr/bin/env python3
"""A one-time hint about the interpreter for a large store.

Request threads and the refresher share one core under the GIL; at 100k runs
that caps the ui at a few dozen requests per second. A free-threaded build
spreads them over every core, and at every store size it is also the leaner
one: a 737k-run ui reached 112 GB RSS after a cold index on 3.14 against 74 GB
on 3.14t, and held 18 GB after 40 minutes on 3.15.2t. The ui only reads the
store, so it can run on its own interpreter, apart from the jobs' environment.
"""
import sys
import threading

from vmn_exp._base import ensure_logger

LARGE_STORE_RECORDS = 10_000
_DOCS = "(see docs/vmn-exp/ui.md, 'Large stores: run the UI on free-threaded Python')"
HINT = (
    "This store has %d runs and this Python has the GIL enabled, which caps the "
    "ui at one core. For a much faster ui, run it on a free-threaded Python:\n\n"
    "  uvx --python 3.15t --from 'vmn-exp[ui]' vmn-exp ui ...\n\n" + _DOCS
)


def gil_enabled():
    is_enabled = getattr(sys, "_is_gil_enabled", None)
    return True if is_enabled is None else is_enabled()


class GilHint:
    def __init__(self, gil_enabled=gil_enabled):
        self._gil_enabled = gil_enabled
        self._given = False
        self._lock = threading.Lock()

    def note(self, records):
        """Log the hint the first time a store of *records* runs warrants it."""
        if records < LARGE_STORE_RECORDS or not self._gil_enabled():
            return
        with self._lock:
            if self._given:
                return
            self._given = True
        ensure_logger().warning(HINT % records)
