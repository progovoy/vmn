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

from version_stamp.core.experiment_index import ExperimentIndex
from version_stamp.core.version_math import app_name_to_tag_name
from version_stamp.ui.readers import experiments as exp_reader
from version_stamp.ui.readers import versions as ver_reader

# Module-level aliases: the direct reads, used when the index is unavailable.
_fetch_experiment_rows = exp_reader.fetch_experiment_rows
_fetch_run_states = exp_reader.fetch_run_states
_fetch_version_rows = ver_reader.list_versions

_LOGGER = logging.getLogger(__name__)


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
        slug = hashlib.sha256(os.path.abspath(root_path).encode()).hexdigest()[:16]
        self._db_path = os.path.join(db_dir, f"{slug}.sqlite")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            " scope TEXT PRIMARY KEY, fingerprint TEXT, payload TEXT)"
        )
        self._conn.commit()
        self._experiments = {}  # app -> ExperimentIndex over this workspace
        self._run_states_of = {}  # app -> run states from its latest refresh

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

    def _experiment_index(self, app_name):
        with self._lock:
            index = self._experiments.get(app_name)
            if index is None:
                index = self._experiments[app_name] = ExperimentIndex(
                    exp_reader.experiment_storage(self.root_path),
                    app_name,
                    cache_path=self._db_path,
                )
            return index

    def _experiment_rows(self, app_name):
        """Leaderboard rows, refreshing the incremental experiment index.

        A metric appended anywhere costs that log's new bytes and a heartbeat
        that one run state — never a re-read of every experiment.
        """
        try:
            index = self._experiment_index(app_name).refresh()
            rows, states = index.rows(), index.run_states()
        except Exception:
            _LOGGER.debug("Experiment index failed; reading directly", exc_info=True)
            rows = _fetch_experiment_rows(self.root_path, app_name)
            states = _fetch_run_states(
                root_path=self.root_path,
                app_name=app_name,
                verstrs=[r["verstr"] for r in rows],
            )
        self._run_states_of[app_name] = states
        return rows

    def _run_states(self, app_name, verstrs):
        """The run states read by the refresh behind ``_experiment_rows``."""
        states = self._run_states_of.get(app_name)
        if states is None:
            self._experiment_rows(app_name)
            states = self._run_states_of[app_name]
        return {verstr: states.get(verstr) for verstr in verstrs}

    def list_experiments(
        self,
        app_name,
        sort=None,
        last=None,
        offset=0,
        limit=None,
        status=None,
        query=None,
    ):
        rows = self._experiment_rows(app_name)
        run_states = self._run_states(app_name, [r["verstr"] for r in rows])
        # Status is derived from the current time, so never from the cache.
        rows = exp_reader.annotate_status(rows, run_states)
        schema = exp_reader.metrics_schema(self.root_path, app_name)
        # ``query`` is a per-request filter over derived rows: never cached.
        return exp_reader.sort_rows(
            exp_reader.apply_filters(rows, status, query),
            schema,
            sort=sort,
            last=last,
            offset=offset,
            limit=limit,
        )

    def list_versions(self, app_name):
        fp = _versions_fingerprint(self.root_path, app_name)
        rows = self._get(f"ver:{app_name}", fp)
        if rows is None:
            rows = _fetch_version_rows(self.root_path, app_name)
            self._put(f"ver:{app_name}", fp, rows)
        return rows
