#!/usr/bin/env python3
"""One named daemon thread running ``work(value)`` for the latest value
submitted per key: a value submitted while an earlier one of its key still
waits replaces it, so a busy worker skips the values it missed instead of
queueing them (the refresher's warming: only the newest generation of an
index is worth warming). Keys are served in the order they first waited.
Failures are logged, never raised.
"""
import logging
import threading

from vmn_exp.core.traced_lock import TracedLock

_LOGGER = logging.getLogger(__name__)
_STOP = object()


class LatestWorker:
    def __init__(self, work, name):
        self._work = work
        self._name = name
        self._pending = {}  # key -> its latest value, in the order keys first waited
        self._busy = False
        self._stopped = False
        self._thread = None
        self._wake = threading.Condition(TracedLock(name))

    def submit(self, key, value):
        """Run ``work(value)`` soon, instead of any value of *key* still waiting."""
        with self._wake:
            if self._stopped:
                return
            self._pending[key] = value
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
                self._thread.start()
            self._wake.notify()

    def idle(self, timeout=None):
        """Whether nothing waits or runs, within *timeout* seconds."""
        with self._wake:
            return self._wake.wait_for(lambda: not self._pending and not self._busy, timeout)

    def stop(self):
        """Drop the waiting values and end the thread after its current work."""
        with self._wake:
            self._stopped = True
            self._pending.clear()
            self._wake.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def _next(self):
        with self._wake:
            self._busy = False
            self._wake.notify_all()
            self._wake.wait_for(lambda: self._pending or self._stopped)
            if self._stopped:
                return _STOP
            self._busy = True
            return self._pending.pop(next(iter(self._pending)))

    def _run(self):
        while self._run_one(self._next()):
            pass

    def _run_one(self, value):
        """False once stopped; returns before the next wait, so the value
        done (a whole generation) is never kept alive meanwhile."""
        if value is _STOP:
            return False
        try:
            self._work(value)
        except Exception:
            _LOGGER.debug("%s failed", self._name, exc_info=True)
        return True
