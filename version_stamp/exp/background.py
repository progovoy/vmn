#!/usr/bin/env python3
"""One background worker that only ever does the newest pending job.

The SDK's slow remote writes — the run state's remote copy, the log sync — must
never run on the heartbeat thread: a hung S3 PUT there is a heartbeat that did
not happen. Both are "catch the remote up" jobs, where a job overtaken by a
newer one is not worth doing, so pending jobs coalesce into the newest and run
one at a time, in order.
"""
import logging
import threading

_LOGGER = logging.getLogger(__name__)
_NOTHING = object()


class Coalescing:
    """Run ``job(item)`` off-thread for the newest submitted *item*."""

    def __init__(self, job, name):
        self._job = job
        self._name = name
        self._cond = threading.Condition()
        self._pending = _NOTHING
        self._closed = False
        self._thread = None

    def submit(self, item=None):
        with self._cond:
            self._pending = item
            self._cond.notify()
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._loop, name=self._name, daemon=True
                )
                self._thread.start()

    def close(self, timeout):
        """Finish what is pending, then stop. False if that took over *timeout*."""
        with self._cond:
            self._closed = True
            self._cond.notify()
            thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _next(self):
        """The next item, or ``_NOTHING`` once closed with nothing pending."""
        with self._cond:
            while self._pending is _NOTHING and not self._closed:
                self._cond.wait()
            item, self._pending = self._pending, _NOTHING
            return item

    def _loop(self):
        while True:
            item = self._next()
            if item is _NOTHING:
                return
            try:
                self._job(item)
            except Exception:
                _LOGGER.debug(f"{self._name} job failed", exc_info=True)
