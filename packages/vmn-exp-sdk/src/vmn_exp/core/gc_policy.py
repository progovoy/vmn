#!/usr/bin/env python3
"""When the cyclic collector runs in a long-lived ui on a free-threaded build.

There every collection stops the whole process and scans everything alive,
frozen objects included (docs/plans/28-measurements.md point 5), and the
automatic trigger fires once RSS grew 10%, which mimalloc's retention alone
keeps causing. At 705k runs that stopped a ui 4-9 s, ten times in 45 minutes.

A pause only gets shorter with fewer live objects (plan 26 F1), so past
:data:`FREE_THREADED_LARGE_RECORDS` runs :class:`GcPolicy` makes them rarer:
automatic collection off, and a ``vmn-gc`` thread collects on its own clock,
publishes or not. Its wait doubles from :data:`GC_MIN_INTERVAL_SEC` up to
:data:`GC_MAX_INTERVAL_SEC` while a collection finds less than
:data:`MUCH_GARBAGE` objects, and halves when one finds more, so uncollected
cycles stay bounded by what the ui makes between two collections. A GIL
build, or a smaller store, keeps CPython's own collector.
"""
import gc
import threading
import time

from vmn_exp.core.gc_pause import set_automatic
from vmn_exp.core.index_load_pool import free_threaded

FREE_THREADED_LARGE_RECORDS = 200_000
GC_MIN_INTERVAL_SEC = 300
GC_MAX_INTERVAL_SEC = 3600
MUCH_GARBAGE = 100_000


def _start_daemon(target):
    threading.Thread(target=target, name="vmn-gc", daemon=True).start()


class GcPolicy:
    def __init__(self, free_threaded=free_threaded, collect=gc.collect,
                 set_automatic=set_automatic, start=_start_daemon, clock=time.monotonic,
                 wall=time.time, min_interval=GC_MIN_INTERVAL_SEC,
                 max_interval=GC_MAX_INTERVAL_SEC):
        self._free_threaded, self._collect, self._set_automatic = free_threaded, collect, set_automatic
        self._start, self._clock, self._wall = start, clock, wall
        self._min, self._max = min_interval, max_interval
        self._interval = min_interval
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._active = False
        self._collections, self._total, self._last, self._last_at = 0, 0.0, None, None
        self._garbage, self._last_garbage = 0, None

    def after_publish(self, records):
        """A generation of *records* runs was just published."""
        with self._lock:
            if self._active or records < FREE_THREADED_LARGE_RECORDS or not self._free_threaded():
                return
            self._active = True
        self._set_automatic(False)
        self._start(self._run)

    def _run(self):
        while not self._stopped.wait(self._interval):
            self.collect_now()

    def stop(self):
        self._stopped.set()

    def collect_now(self):
        """Collect, then return how long to wait before the next one."""
        started, self._last_at = self._clock(), self._wall()
        found = self._collect()
        self._last = self._clock() - started
        self._total += self._last
        self._collections += 1
        self._garbage += found
        self._last_garbage = found
        if found >= MUCH_GARBAGE:
            self._interval = max(self._min, self._interval / 2)
        else:
            self._interval = min(self._max, self._interval * 2)
        return self._interval

    def stats(self):
        return {
            "active": self._active,
            "interval_sec": self._interval,
            "collections": self._collections,
            "total_ms": round(self._total * 1000, 3),
            "last_ms": None if self._last is None else round(self._last * 1000, 3),
            "last_at": self._last_at,
            "garbage": self._garbage,
            "last_garbage": self._last_garbage,
        }


POLICY = GcPolicy()
