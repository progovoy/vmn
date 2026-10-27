#!/usr/bin/env python3
"""Self-healing and manual resync of one workspace's cache (plan 11 §4.6).

:meth:`WorkspaceCache.tick` (every refresh tick, throttled to ``check_sec``)
asks the cache's health probe (:mod:`vmn_exp.ui.cache_health`) and starts a
background rebuild on any problem but derived tables of an older version,
which it re-derives in the background from the file's own records instead
(:mod:`vmn_exp.core.index_derive`); it also tidies the cache file now and
then (:mod:`vmn_exp.ui.cache_tidy`: superseded files, an oversized WAL).
:meth:`WorkspaceCache.resync` is the manual side: a plain one makes every
watched index re-check all its records' signatures at its next refresh;
``full=True`` rebuilds.

A rebuild loads every noted app afresh into a :mod:`vmn_exp.ui.cache_rebuild`
target while the live indexes keep serving their snapshots, switches the
target over, then has each live index adopt its rebuilt records.
"""
import logging
import threading
import time

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.index_store_schema import DERIVED
from vmn_exp.ui.cache_rebuild import MemoryTarget, SqliteSwap
from vmn_exp.ui.cache_tidy import CacheTidy

_LOGGER = logging.getLogger(__name__)
CHECK_SEC = 1.0


def _build(storage, app, store, like):
    """*app* loaded afresh into *store*, swept like the live index *like*
    (journaled only once loaded: a journaled sweep lists behind serving)."""
    fresh = ExperimentIndex(storage, app, cache_store=store)
    fresh.full_sweep_sec = like.full_sweep_sec
    fresh.refresh().journaled = like.journaled
    return fresh


def _rederive(path):
    """Re-derive every app the file at *path* holds rows of an older version
    for (opening it marks them)."""
    store = SqliteStore(path)
    try:
        for app in store.pending_apps():
            store.derive(app)
    finally:
        store.close()


class WorkspaceCache:
    def __init__(self, name, cache_path=None, health=None, journal_of=None,
                 check_sec=CHECK_SEC, target_of=None, clock=time.monotonic):
        self.name = name
        self._path = cache_path
        self._health = health
        self._journal_of = journal_of or (lambda: None)
        self._target_of = target_of or (
            lambda: SqliteSwap(cache_path) if cache_path else MemoryTarget())
        self._check_sec, self._clock, self._checked_at = check_sec, clock, None
        self.tidy = CacheTidy(cache_path, clock) if cache_path else None
        self._apps = {}  # app -> (storage, index_of)
        self._swapped = []
        self._lock = threading.Lock()
        self._thread = self._deriver = None
        self._progress = {"done": 0, "total": 0}
        self._reason, self.rebuilds = None, 0

    def note(self, app, storage, index_of):
        """*app* is served from ``index_of()``, reading *storage*."""
        with self._lock:
            self._apps[app] = (storage, index_of)

    def on_swapped(self, callback):
        """Call *callback* after each rebuild switched over."""
        self._swapped.append(callback)

    def tick(self):
        """Start a rebuild when the probe finds a problem; the problem, or None."""
        if self.tidy is not None:
            self.tidy.tick()
        now = self._clock()
        if self._checked_at is not None and now - self._checked_at < self._check_sec:
            return None
        self._checked_at = now
        if self._health is None or self.rebuilding:
            return None
        problem = self._health.problem()
        if problem == DERIVED:
            self._derive_in_background()
        elif problem:
            _LOGGER.warning("Workspace %s cache %s; rebuilding", self.name, problem)
            self._start(problem)
        return problem

    def resync(self, full=False):
        if full:
            self._start("requested")
        else:
            for index in self._live().values():
                index.reconcile()
        return self.status()

    @property
    def rebuilding(self):
        return _alive(self._thread)

    def wait(self, timeout=None):
        """True once no rebuild or re-derive is running (within *timeout*)."""
        for thread in (self._thread, self._deriver):
            if thread is not None:
                thread.join(timeout)
        return not self.rebuilding and not _alive(self._deriver)

    def status(self):
        indexes = self._live()
        apps = {app: _app_status(index) for app, index in indexes.items()}
        return {
            "workspace": self.name,
            "state": "rebuilding" if self.rebuilding else "idle",
            "last_rebuild_reason": self._reason,
            "rebuilds": self.rebuilds,
            "progress": dict(self._progress),
            "drift": sum(a["drift"] for a in apps.values()),
            "journal_lag_sec": self._journal_lag(),
            "apps": apps,
        }

    def _live(self):
        with self._lock:
            apps = dict(self._apps)
        return {app: index_of() for app, (_, index_of) in apps.items()}

    def _journal_lag(self):
        journal = self._journal_of()
        last_ms = journal.cursor.get("last_seen_ms") if journal is not None else None
        return None if last_ms is None else max(0.0, time.time() - last_ms / 1000)

    def _derive_in_background(self):
        with self._lock:
            if _alive(self._deriver):
                return
            _LOGGER.info("Workspace %s cache rows are from an older vmn-exp;"
                         " re-deriving them from its records", self.name)
            self._deriver = threading.Thread(
                target=self._derive_logged, daemon=True, name="vmn-ui-cache-derive")
            self._deriver.start()

    def _derive_logged(self):
        try:
            _rederive(self._path)
        except Exception:
            _LOGGER.warning("Re-deriving workspace %s's cache failed", self.name, exc_info=True)

    def _start(self, reason):
        with self._lock:
            if self.rebuilding:
                return
            self._reason = reason
            self._thread = threading.Thread(
                target=self._rebuild_logged, daemon=True, name="vmn-ui-cache-rebuild")
            self._thread.start()

    def _rebuild_logged(self):
        try:
            self._rebuild()
        except Exception:
            _LOGGER.warning("Rebuilding workspace %s's cache failed", self.name, exc_info=True)

    def _rebuild(self):
        with self._lock:
            apps = dict(self._apps)
        live = {app: index_of() for app, (_, index_of) in apps.items()}
        self._progress = {"done": 0, "total": sum(i.record_count for i in live.values())}
        target, built = self._target_of(), {}
        for app, (storage, _) in apps.items():
            built[app] = _build(storage, app, target.store_for(app), live[app])
            target.built(app, built[app])
            self._progress["done"] += built[app].record_count
        self._progress["total"] = max(self._progress["total"], self._progress["done"])
        target.commit()
        for app, fresh in built.items():
            live[app].adopt(fresh, target.live_store(app))
        if self._health is not None:
            self._health.rearm()
        self.rebuilds += 1
        for callback in self._swapped:
            callback()


def _alive(thread):
    return thread is not None and thread.is_alive()


def _app_status(index):
    return {
        "generation": index.generation,
        "records": index.record_count,
        "drift": index.drift,
        "last_reconcile_at": index.last_reconcile_at,
    }
