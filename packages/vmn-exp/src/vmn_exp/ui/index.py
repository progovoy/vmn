#!/usr/bin/env python3
"""Derived, disposable SQLite cache for vmn-exp ui reads.

The source of truth stays in git tags and ``.vmn/`` files — this index only
memoizes their parsed form: experiments through the incremental
:class:`~version_stamp.core.experiment_index.ExperimentIndex` (only the files
that changed are read again), versions keyed by the tag list. Deleting the
database loses nothing. It lives under the server's data dir, never inside the repo,
so it can't dirty a workspace's git status; with ``--no-index`` it is kept in
memory only.
"""
import hashlib
import logging
import os
import threading

import vmn_exp.core.index as experiment_index
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.status import MIN_STALE_SEC
from vmn_exp.ui.readers import experiments as exp_reader
from vmn_exp.ui.readers import versions as ver_reader
from vmn_exp.ui.refresher import InlineRefresher
from vmn_exp.ui.tree_cache import versions_fingerprint

_LOGGER = logging.getLogger(__name__)
_INLINE = InlineRefresher()


def app_snapshot(storage, app_name, cache_path, refresher=_INLINE, schema=None,
                 journal=None, reconcile_sec=None, *, index_clock=None,
                 min_stale_sec=MIN_STALE_SEC):
    """The app's :class:`IndexSnapshot`, from the shared index at *cache_path*.

    A :class:`~vmn_exp.ui.refresher.Refresher` keeps the index fresh in
    the background and this returns at once; the default
    :class:`~vmn_exp.ui.refresher.InlineRefresher` refreshes it first,
    so a request sees every write before it. Falls back to a direct read when
    the index fails. Rows follow the metrics *schema* passed (see
    :meth:`~vmn_exp.core.index_snapshot.IndexSnapshot.summarized`).
    *index_clock*, *min_stale_sec*: a new shared index's (see
    :func:`~vmn_exp.core.index.shared_index`).
    """
    return _snapshot_of(
        lambda: experiment_index.shared_index(storage, app_name, cache_path, clock=index_clock,
                                              min_stale_sec=min_stale_sec),
        storage,
        app_name,
        refresher,
        schema,
        journal,
        reconcile_sec,
    )


def refresh_app(storage, app_name, cache_path, *, index_clock=None, min_stale_sec=MIN_STALE_SEC):
    """Refresh the shared index now, so a server edit shows at once."""
    experiment_index.shared_index(storage, app_name, cache_path, clock=index_clock,
                                  min_stale_sec=min_stale_sec).refresh()


def snapshot_of_index(index, storage, app_name, refresher=_INLINE, schema=None,
                      journal=None, reconcile_sec=None):
    """:func:`app_snapshot` of an index built elsewhere (the Postgres one)."""
    return _snapshot_of(lambda: index, storage, app_name, refresher, schema, journal,
                        reconcile_sec)


def _snapshot_of(index_of, storage, app_name, refresher, schema=None, journal=None,
                 reconcile_sec=None):
    try:
        index = index_of()
        if refresher.full_sweep_sec is not None:
            index.full_sweep_sec = reconcile_sec or refresher.full_sweep_sec
        if journal is None:
            return refresher.snapshot(index).summarized(schema, stale_ok=True)
        return refresher.snapshot(index, journal).summarized(schema, stale_ok=True)
    except Exception:
        _LOGGER.warning("Experiment index failed; reading directly", exc_info=True)
        return experiment_index.direct_snapshot(storage, app_name, schema)


def _db_path(db_dir, source, prefix=""):
    slug = hashlib.sha256(source.encode()).hexdigest()[:16]
    return os.path.join(db_dir, f"{prefix}{slug}.sqlite")


def s3_cache_path(db_dir, ws):
    """Where a store workspace's index persists, one database per store."""
    os.makedirs(db_dir, exist_ok=True)
    return _db_path(db_dir, ws.store, "s3-")


class WorkspaceIndex:
    """Per-workspace read cache. Thread-safe for server use.

    Without *db_dir* (``--no-index``) nothing is persisted: the experiment
    indexes and the versions cache live in this object's memory only.
    *index_clock* is the indexes' and the cache's (see
    :class:`~vmn_exp.core.index.ExperimentIndex`; None: their modules' own),
    *min_stale_sec* the indexes' stuck floor.
    """

    def __init__(self, root_path, db_dir=None, *, processes, clock, env, index_clock=None,
                 min_stale_sec=MIN_STALE_SEC):
        self._index_clock, self._min_stale_sec = index_clock, min_stale_sec
        self.root_path = root_path
        self._processes = processes  # lists the app's tags (the versions cache key)
        self._db_path = None
        if db_dir is not None:
            os.makedirs(db_dir, exist_ok=True)
            self._db_path = _db_path(db_dir, os.path.abspath(root_path))
        self._lock = threading.Lock()
        self._in_memory = {}  # app name -> unpersisted ExperimentIndex
        self._cache = SqliteStore(self._db_path or ":memory:", clock=index_clock)
        self._storage = exp_reader.experiment_storage(root_path, clock, env)

    @property
    def db_path(self):
        return self._db_path

    def index_of(self, app_name):
        """The index :meth:`snapshot` serves *app_name* from."""
        if self._db_path:
            return experiment_index.shared_index(self._storage, app_name, self._db_path,
                                                 clock=self._index_clock,
                                                 min_stale_sec=self._min_stale_sec)
        return self._in_memory_index(app_name)

    def reopen(self):
        """Reconnect the versions cache (a rebuild swapped the file)."""
        with self._lock:
            self._cache = SqliteStore(self._db_path or ":memory:", clock=self._index_clock)

    @property
    def storage(self):
        """The workspace's experiment storage, shared by every request."""
        return self._storage

    def snapshot(self, app_name, refresher=_INLINE, schema=None):
        """The app's current :class:`IndexSnapshot` (see :func:`app_snapshot`)."""
        if self._db_path:
            return app_snapshot(self._storage, app_name, self._db_path, refresher, schema,
                                index_clock=self._index_clock,
                                min_stale_sec=self._min_stale_sec)
        return _snapshot_of(
            lambda: self._in_memory_index(app_name),
            self._storage, app_name, refresher, schema,
        )

    def _in_memory_index(self, app_name):
        with self._lock:
            if app_name not in self._in_memory:
                self._in_memory[app_name] = experiment_index.ExperimentIndex(
                    self._storage, app_name, clock=self._index_clock,
                    min_stale_sec=self._min_stale_sec,
                )
            return self._in_memory[app_name]

    def list_versions(self, app_name):
        fp = versions_fingerprint(self.root_path, app_name, self._processes)
        with self._lock:
            rows = self._cache.kv_get(f"ver:{app_name}", fp)
        if rows is None:
            rows = ver_reader.list_versions(self.root_path, app_name)
            with self._lock:
                self._cache.kv_put(f"ver:{app_name}", fp, rows)
        return rows
