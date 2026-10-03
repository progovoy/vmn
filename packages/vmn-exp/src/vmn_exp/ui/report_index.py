"""One :class:`~vmn_exp.reports.index.ReportIndex` per workspace (plan 13 §8.2).

Each persists in its own SQLite kv under the server's index dir. Refreshed on
the request path: with background refresh at most once a second from the
journal (a full listing every few minutes), else fully on every request, so a
request sees every write before it — like the experiment indexes.
"""
import hashlib
import os
import threading
import time

from vmn_exp.core.index_store import SqliteStore
from vmn_exp.reports.index import FULL_SWEEP_SEC, ReportIndex

FOLLOW_INTERVAL_SEC = 1.0


class ReportIndexes:
    def __init__(self, db_dir=None, background=False):
        self._db_dir = db_dir
        self._background = background
        self._indexes = {}  # ws name -> (index, last refresh time)
        self._lock = threading.Lock()

    def get(self, ws, storage):
        """*ws*'s index over *storage*, refreshed as configured."""
        with self._lock:
            if ws.name not in self._indexes:
                self._indexes[ws.name] = [self._new(ws, storage), None]
            entry = self._indexes[ws.name]
        now = time.monotonic()
        if not self._background or entry[1] is None or now - entry[1] >= FOLLOW_INTERVAL_SEC:
            entry[0].refresh()
            entry[1] = now
        return entry[0]

    def forget(self, ws_name):
        with self._lock:
            self._indexes.pop(ws_name, None)

    def _new(self, ws, storage):
        sweep = FULL_SWEEP_SEC if self._background else 0
        return ReportIndex(storage, cache=self._cache(ws), full_sweep_sec=sweep)

    def _cache(self, ws):
        if self._db_dir is None:
            return None
        os.makedirs(self._db_dir, exist_ok=True)
        source = ws.store or os.path.abspath(ws.path)
        slug = hashlib.sha256(source.encode()).hexdigest()[:16]
        return SqliteStore(os.path.join(self._db_dir, f"reports-{slug}.sqlite"))
