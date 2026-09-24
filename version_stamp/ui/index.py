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
import subprocess
import threading

from version_stamp.core import experiment_index
from version_stamp.core.version_math import app_name_to_tag_name
from version_stamp.ui.readers import experiments as exp_reader
from version_stamp.ui.readers import versions as ver_reader

# Module-level aliases: the direct reads, used when the index is unavailable.
_fetch_experiment_rows = exp_reader.fetch_experiment_rows
_fetch_run_states = exp_reader.fetch_run_states
_fetch_version_rows = ver_reader.list_versions

_LOGGER = logging.getLogger(__name__)

# With a background refresher: names + live records each refresh, a full
# listing this often (see experiment_index_sweep).
FULL_SWEEP_SEC = 30


def app_snapshot(storage, app_name, cache_path, refresher=None):
    """The app's :class:`IndexSnapshot`, from the shared index at *cache_path*.

    With a :class:`~version_stamp.ui.refresher.Refresher` the index is kept
    fresh in the background (fast tier) and this returns at once; without
    one it is refreshed inline, so a request sees every write before it.
    Falls back to a direct read when the index fails.
    """
    if refresher is None:
        return experiment_index.indexed_snapshot(storage, app_name, cache_path)
    try:
        index = experiment_index.shared_index(
            storage, app_name, cache_path, full_sweep_sec=FULL_SWEEP_SEC
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


def _versions_fingerprint(root_path, app_name):
    """Cheap staleness signal: the app's tag list (one local git call)."""
    prefix = app_name_to_tag_name(app_name)
    result = subprocess.run(
        ["git", "tag", "--list", f"{prefix}_*"],
        capture_output=True,
        text=True,
        cwd=root_path,
    )
    if result.returncode != 0:
        return "error"
    return hashlib.sha256(result.stdout.encode()).hexdigest()


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

    def experiment_rows(self, app_name):
        """``(rows, run_states)``, refreshing the incremental experiment index.

        A metric appended anywhere costs that log's new bytes and a heartbeat
        that one run state — never a re-read of every experiment. The index is
        the process-wide one for this checkout, persisted in this db.
        """
        try:
            index = experiment_index.shared_index(
                self._storage, app_name, cache_path=self._db_path
            ).refresh()
            return index.rows(), index.run_states()
        except Exception:
            _LOGGER.debug("Experiment index failed; reading directly", exc_info=True)
            rows = _fetch_experiment_rows(self.root_path, app_name)
            states = _fetch_run_states(
                root_path=self.root_path,
                app_name=app_name,
                verstrs=[r["verstr"] for r in rows],
            )
            return rows, states

    def snapshot(self, app_name, refresher=None):
        """The app's current :class:`IndexSnapshot` (see :func:`app_snapshot`)."""
        return app_snapshot(self._storage, app_name, self._db_path, refresher)

    def list_experiments(self, app_name, **filters):
        rows, run_states = self.experiment_rows(app_name)
        schema = exp_reader.metrics_schema(self.root_path, app_name)
        return exp_reader.leaderboard(rows, run_states, schema, **filters)

    def list_versions(self, app_name):
        fp = _versions_fingerprint(self.root_path, app_name)
        rows = self._get(f"ver:{app_name}", fp)
        if rows is None:
            rows = _fetch_version_rows(self.root_path, app_name)
            self._put(f"ver:{app_name}", fp, rows)
        return rows
