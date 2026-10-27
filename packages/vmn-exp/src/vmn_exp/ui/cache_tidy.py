#!/usr/bin/env python3
"""The server's periodic tidy of one SQLite cache file: what its long-lived
connections never do by themselves.

At most every :data:`TIDY_SEC` (from :meth:`WorkspaceCache.tick
<vmn_exp.ui.cache_resync.WorkspaceCache.tick>`), in a background thread so
a request never waits on it: superseded generations nothing holds any more
are removed (:func:`vmn_exp.core.sqlite_files.sweep`), and a WAL grown past
its limit with no write since to checkpoint it is checkpointed. Best-effort:
a busy file is left for the next tidy.
"""
import logging
import os
import sqlite3
import threading

from vmn_exp.core import sqlite_files
from vmn_exp.core.sqlite_conn import checkpoint, connect, wal_oversized

TIDY_SEC = 60.0
_LOGGER = logging.getLogger(__name__)


class CacheTidy:
    def __init__(self, path, clock, every_sec=TIDY_SEC):
        self.path, self._clock, self._every_sec = path, clock, every_sec
        self._tidied_at = None
        self._thread = None

    def tick(self):
        """Start a tidy when the last one is :data:`TIDY_SEC` old and done."""
        now = self._clock()
        if self._tidied_at is not None and now - self._tidied_at < self._every_sec:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._tidied_at = now
        self._thread = threading.Thread(target=self._tidy, daemon=True,
                                        name="vmn-ui-cache-tidy")
        self._thread.start()

    def wait(self, timeout=None):
        """Wait for a running tidy (for tests and shutdown)."""
        if self._thread is not None:
            self._thread.join(timeout)

    def _tidy(self):
        try:
            sqlite_files.sweep(self.path)
            _checkpoint_if_oversized(sqlite_files.live_path(self.path))
        except (sqlite3.Error, OSError):
            _LOGGER.debug("Tidying the cache file %s failed", self.path, exc_info=True)


def _checkpoint_if_oversized(file):
    if not os.path.exists(file) or not wal_oversized(file):
        return
    conn = connect(file)
    try:
        checkpoint(conn)
    finally:
        conn.close()
