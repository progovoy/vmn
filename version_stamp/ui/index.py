#!/usr/bin/env python3
"""Derived, disposable SQLite cache for vmn ui reads.

The source of truth stays in git tags and ``.vmn/`` files — this index only
memoizes their parsed form, keyed by cheap staleness fingerprints (directory
mtimes for experiments, the tag list for versions). Deleting the database
loses nothing. It lives under the server's data dir, never inside the repo,
so it can't dirty a workspace's git status.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import threading

from version_stamp.core.version_math import app_name_to_tag_name
from version_stamp.ui.readers import experiments as exp_reader
from version_stamp.ui.readers import versions as ver_reader

# Module-level aliases: the expensive fetches the cache guards.
_fetch_experiment_rows = exp_reader.fetch_experiment_rows
_fetch_version_rows = ver_reader.list_versions


def _experiments_fingerprint(root_path, app_name):
    """Cheap staleness signal: names + mtimes of every experiment dir's files."""
    base = os.path.join(
        root_path, ".vmn", app_name.replace("/", os.sep), "experiments"
    )
    h = hashlib.sha256()
    try:
        for entry in sorted(os.scandir(base), key=lambda e: e.name):
            if not entry.is_dir():
                continue
            for fname in ("metadata.yml", "log.yml"):
                try:
                    st = os.stat(os.path.join(entry.path, fname))
                    h.update(f"{entry.name}/{fname}:{st.st_mtime_ns}\n".encode())
                except OSError:
                    continue
    except OSError:
        return "empty"
    return h.hexdigest()


def _versions_fingerprint(root_path, app_name):
    """Cheap staleness signal: the app's tag list (one local git call)."""
    prefix = app_name_to_tag_name(app_name)
    result = subprocess.run(
        ["git", "tag", "--list", f"{prefix}_*"],
        capture_output=True, text=True, cwd=root_path,
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

    def list_experiments(self, app_name, sort=None, last=None):
        fp = _experiments_fingerprint(self.root_path, app_name)
        # v2: rows carry the storage-order idx; the scope bump invalidates
        # cached payloads from before it existed.
        rows = self._get(f"exp:v2:{app_name}", fp)
        if rows is None:
            rows = _fetch_experiment_rows(self.root_path, app_name)
            self._put(f"exp:v2:{app_name}", fp, rows)
        schema = exp_reader.metrics_schema(self.root_path, app_name)
        return exp_reader.sort_rows(rows, schema, sort=sort, last=last)

    def list_versions(self, app_name):
        fp = _versions_fingerprint(self.root_path, app_name)
        rows = self._get(f"ver:{app_name}", fp)
        if rows is None:
            rows = _fetch_version_rows(self.root_path, app_name)
            self._put(f"ver:{app_name}", fp, rows)
        return rows
