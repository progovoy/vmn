#!/usr/bin/env python3
"""Keeps the experiment indexes the dashboard is looking at fresh, off the
request path.

A request asks :meth:`Refresher.snapshot` for an index's current snapshot:
that marks the index watched and makes sure a daemon thread is refreshing it
every ``interval_sec``. The thread exits once nobody asked for ``idle_sec``,
so an app no one looks at costs nothing; the next request starts it again.
Only the very first request of an index waits (for its initial load, which
the persisted SQLite store makes fast). A refresh that fails is logged and
the last snapshot keeps being served.
"""
import logging
import threading
import time

REFRESH_INTERVAL_SEC = 1.0
IDLE_SEC = 60.0

_LOGGER = logging.getLogger(__name__)


class _Watch:
    def __init__(self):
        self.touched_at = time.monotonic()
        self.thread = None
        self.failing = False


class Refresher:
    def __init__(self, interval_sec=REFRESH_INTERVAL_SEC, idle_sec=IDLE_SEC):
        self.interval_sec = interval_sec
        self.idle_sec = idle_sec
        self._watches = {}  # index -> _Watch
        self._lock = threading.Lock()
        self._stopped = threading.Event()

    def snapshot(self, index):
        """*index*'s current snapshot, keeping *index* refreshed from now on."""
        self._watch(index)
        return index.snapshot()

    def watching(self, index):
        watch = self._watches.get(index)
        return bool(watch and watch.thread and watch.thread.is_alive())

    def stop(self):
        """End every refresh thread (for tests and shutdown)."""
        self._stopped.set()
        with self._lock:
            threads = [w.thread for w in self._watches.values() if w.thread]
        for thread in threads:
            thread.join()

    def _watch(self, index):
        with self._lock:
            watch = self._watches.setdefault(index, _Watch())
            watch.touched_at = time.monotonic()
            if watch.thread is None and not self._stopped.is_set():
                watch.thread = threading.Thread(
                    target=self._run, args=(index, watch), daemon=True,
                    name="vmn-ui-refresh",
                )
                watch.thread.start()

    def _run(self, index, watch):
        # Refresh at once: a restart after idling catches up before it waits.
        while not self._idle(watch):
            self._refresh(index, watch)
            if self._stopped.wait(self.interval_sec):
                return

    def _idle(self, watch):
        with self._lock:
            if time.monotonic() - watch.touched_at < self.idle_sec:
                return False
            watch.thread = None
            return True

    def _refresh(self, index, watch):
        try:
            index.refresh()
        except Exception:
            # Once per failure streak: a broken store would log every second.
            log = _LOGGER.debug if watch.failing else _LOGGER.warning
            log("Background index refresh failed; serving the last snapshot", exc_info=True)
            watch.failing = True
        else:
            watch.failing = False
