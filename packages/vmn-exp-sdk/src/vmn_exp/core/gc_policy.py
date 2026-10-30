#!/usr/bin/env python3
"""When the cyclic collector runs in a long-lived ui on a free-threaded build.

There every collection stops the whole process and scans every tracked object
(the generation argument is ignored), and the automatic trigger fires once
RSS grew 10%, which mimalloc's retention alone keeps causing. At 705k runs
that stopped a ui 4-9 s at random moments, on whichever thread allocated.

Serving generations makes no cyclic garbage (test_ft_gc_policy_generations),
so past :data:`FREE_THREADED_LARGE_RECORDS` runs :class:`GcPolicy` turns
automatic collection off and collects right after a publish, on the thread
that published, at most every :data:`GC_MIN_INTERVAL_SEC`; it freezes what
survives, so the next one scans only what is new (plan 26 decision 5). A GIL
build, or a smaller store, keeps CPython's own collector.
"""
import threading
import time

from vmn_exp.core.gc_pause import freeze_long_lived, set_automatic
from vmn_exp.core.index_load_pool import free_threaded

FREE_THREADED_LARGE_RECORDS = 200_000
GC_MIN_INTERVAL_SEC = 300


class GcPolicy:
    def __init__(self, free_threaded=free_threaded, clock=time.monotonic,
                 collect=freeze_long_lived, set_automatic=set_automatic, wall=time.time):
        self._free_threaded, self._clock, self._wall = free_threaded, clock, wall
        self._collect, self._set_automatic = collect, set_automatic
        self._lock = threading.Lock()
        self._active = False
        self._due_at = None  # clock time of the next collection
        self._collections, self._total, self._last, self._last_at = 0, 0.0, None, None

    def after_publish(self, records):
        """A generation of *records* runs was just published on this thread."""
        if not self._lock.acquire(blocking=False):
            return  # another index's publish is collecting now
        try:
            if not self._active and not self._activate(records):
                return
            if self._due_at is None or self._clock() >= self._due_at:
                self._collect_now()
        finally:
            self._lock.release()

    def _activate(self, records):
        if records < FREE_THREADED_LARGE_RECORDS or not self._free_threaded():
            return False
        self._set_automatic(False)
        self._active = True
        return True

    def _collect_now(self):
        started, self._last_at = self._clock(), self._wall()
        self._collect()
        self._last = self._clock() - started
        self._total += self._last
        self._collections += 1
        self._due_at = self._clock() + GC_MIN_INTERVAL_SEC

    def stats(self):
        return {
            "active": self._active,
            "interval_sec": GC_MIN_INTERVAL_SEC,
            "collections": self._collections,
            "total_ms": round(self._total * 1000, 3),
            "last_ms": None if self._last is None else round(self._last * 1000, 3),
            "last_at": self._last_at,
        }


POLICY = GcPolicy()
