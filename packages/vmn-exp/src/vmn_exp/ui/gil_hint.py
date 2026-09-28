#!/usr/bin/env python3
"""A one-time hint to serve a large store from a free-threaded Python.

Request threads and the refresher share one core under the GIL; at 100k runs
that caps the ui at a few dozen requests per second. A free-threaded build
(3.14t) spreads them over every core. The ui only reads the store, so it can
run on its own interpreter, apart from the jobs' environment.
"""
import sys
import threading

from vmn_exp._base import ensure_logger

LARGE_STORE_RECORDS = 10_000
HINT = (
    "This store has %d runs and this Python has the GIL enabled, which caps the "
    "ui at one core. For a much faster ui, run it on a free-threaded Python:\n\n"
    "  uvx --python 3.14t --from 'vmn-exp[ui]' vmn-exp ui ...\n\n"
    "(see docs/ui.md, 'Large stores: run the UI on free-threaded Python')"
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
        if records < LARGE_STORE_RECORDS:
            return
        with self._lock:
            if self._given:
                return
            self._given = True
        if self._gil_enabled():
            ensure_logger().warning(HINT % records)
