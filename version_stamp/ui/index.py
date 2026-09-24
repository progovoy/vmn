#!/usr/bin/env python3
"""Derived, disposable SQLite cache for vmn ui reads.

The source of truth stays in git tags and ``.vmn/`` files — this index only
memoizes their parsed form: experiments through the incremental
:class:`~version_stamp.core.experiment_index.ExperimentIndex` (only the files
that changed are read again), versions keyed by the tag list. Deleting the
database loses nothing. It lives under the server's data dir, never inside the repo,
so it can't dirty a workspace's git status.
"""
import hashlib
import json
import logging
import os
import sqlite3
import threading

from version_stamp.core import experiment_index
from version_stamp.ui.readers import experiments as exp_reader
from version_stamp.ui.readers import versions as ver_reader
from version_stamp.ui.refresher import InlineRefresher
from version_stamp.ui.tree_cache import versions_fingerprint

_LOGGER = logging.getLogger(__name__)
_INLINE = InlineRefresher()


def app_snapshot(storage, app_name, cache_path, refresher=_INLINE):
    """The app's :class:`IndexSnapshot`, from the shared index at *cache_path*.

    A :class:`~version_stamp.ui.refresher.Refresher` keeps the index fresh in
    the background and this returns at once; the default
    :class:`~version_stamp.ui.refresher.InlineRefresher` refreshes it first,
    so a request sees every write before it. Falls back to a direct read when
    the index fails.
    """
    try:
        index = experiment_index.shared_index(
            storage, app_name, cache_path, full_sweep_sec=refresher.full_sweep_sec
        )
        return refresher.snapshot(index)
    except Exception:
        _LOGGER.warning("Experiment index failed; reading directly", exc_info=True)
        return experiment_index.direct_snapshot(storage, app_name)


def _db_path(db_dir, source, prefix=""):
    slug = hashlib.sha256(source.encode()).hexdigest()[:16]
    return os.path.join(db_dir, f"{prefix}{slug}.sqlite")


def s3_cache_path(db_dir, ws):
    """Where an S3 workspace's index persists, one database per bucket+prefix."""
    os.makedirs(db_dir, exist_ok=True)
    return _db_path(db_dir, repr((ws.endpoint_url, ws.bucket, ws.prefix)), "s3-")


class WorkspaceIndex:
    """Per-workspace read cache. Thread-safe for server use."""

    def __init__(self, root_path, db_dir):
        self.root_path = root_path
        os.makedirs(db_dir, exist_ok=True)
        self._db_path = _db_path(db_dir, os.path.abspath(root_path))
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            " scope TEXT PRIMARY KEY, fingerprint TEXT, payload TEXT)"
        )
        self._conn.commit()
        self._storage = exp_reader.experiment_storage(root_path)

    def _get(self, scope, fingerprint):
        with self._lock:
            row = self._conn.execute(
                "SELECT fingerprint, payload FROM cache WHERE scope = ?", (scope,)
            ).fetchone()
        if row and row[0] == fingerprint:
            return json.loads(row[1])
        return None

    def _put(self, scope, fingerprint, payload):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (scope, fingerprint, payload)"
                " VALUES (?, ?, ?)",
                (scope, fingerprint, json.dumps(payload)),
            )
            self._conn.commit()

    def snapshot(self, app_name, refresher=_INLINE):
        """The app's current :class:`IndexSnapshot` (see :func:`app_snapshot`)."""
        return app_snapshot(self._storage, app_name, self._db_path, refresher)

    def list_versions(self, app_name):
        fp = versions_fingerprint(self.root_path, app_name)
        rows = self._get(f"ver:{app_name}", fp)
        if rows is None:
            rows = ver_reader.list_versions(self.root_path, app_name)
            self._put(f"ver:{app_name}", fp, rows)
        return rows
