"""One :class:`~vmn_exp.reports.index.ReportIndex` per workspace (plan 13 §8.2).

Each persists in its own SQLite kv under the server's index dir. With
background refresh a request starts a refresh at most once a second on a
daemon thread (one in flight per workspace) and reads the counts as they are
— a journal catch-up can take minutes, and a list waiting on it waits for
comment counts; else each request refreshes fully first, so it sees every
write before it — like the experiment indexes. A store
workspace whose journal follower runs (*journal_of*) feeds its index instead:
the request path then reads no journal.
"""
import hashlib
import logging
import os
import threading
import time

from vmn_exp.core.activity import activity
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.reports.index import FULL_SWEEP_SEC, ReportIndex

FOLLOW_INTERVAL_SEC = 1.0

_LOGGER = logging.getLogger(__name__)


class ReportIndexes:
    def __init__(self, db_dir=None, background=False, journal_of=lambda ws_name: None):
        self._db_dir = db_dir
        self._background = background
        self._journal_of = journal_of
        self._indexes = {}  # ws name -> [index, last refresh time]
        self._refreshing = set()  # ws names with a background refresh in flight
        self._lock = threading.Lock()

    def get(self, ws, storage):
        """*ws*'s index over *storage*, refreshed as configured."""
        with self._lock:
            if ws.name not in self._indexes:
                self._indexes[ws.name] = [self._new(ws, storage), None]
            entry = self._indexes[ws.name]
        journal = self._journal_of(ws.name)
        if journal is not None:
            journal.feed_reports(entry[0])
        if not self._background:
            entry[0].refresh()
            return entry[0]
        now = time.monotonic()
        with self._lock:
            due = entry[1] is None or now - entry[1] >= FOLLOW_INTERVAL_SEC
            if due and ws.name not in self._refreshing:
                self._refreshing.add(ws.name)
                entry[1] = now
                threading.Thread(target=self._refresh, args=(ws.name, entry), daemon=True,
                                 name="vmn-ui-reports").start()
        return entry[0]

    def _refresh(self, ws_name, entry):
        try:
            with activity("report index refresh", key=ws_name):
                entry[0].refresh()
        except Exception:
            _LOGGER.warning("Refreshing the report index failed", exc_info=True)
        finally:
            with self._lock:
                entry[1] = time.monotonic()
                self._refreshing.discard(ws_name)

    def forget(self, ws_name):
        with self._lock:
            self._indexes.pop(ws_name, None)

    def _new(self, ws, storage):
        sweep = FULL_SWEEP_SEC if self._background else 0
        return ReportIndex(storage, cache=self._cache(ws), full_sweep_sec=sweep, name=ws.name)

    def _cache(self, ws):
        if self._db_dir is None:
            return None
        os.makedirs(self._db_dir, exist_ok=True)
        source = ws.store or os.path.abspath(ws.path)
        slug = hashlib.sha256(source.encode()).hexdigest()[:16]
        return SqliteStore(os.path.join(self._db_dir, f"reports-{slug}.sqlite"))
