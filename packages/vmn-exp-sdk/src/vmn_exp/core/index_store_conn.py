#!/usr/bin/env python3
"""The connection behind a :class:`vmn_exp.core.index_store.SqliteStore`:
opened lazily, retried, recovered, never fatal (plan 25 §2).

- An open that fails (locked, read-only, missing dir) is retried on a later
  use, with a backoff doubling up to :data:`MAX_BACKOFF_SEC`.
- A file written by a newer schema is left alone: the store stays off for
  this process.
- A file of older records is left untouched too: the store continues in a
  new generation file (:mod:`vmn_exp.core.index_store_upgrade`).
- A corrupt file is rebuilt beside it: a new generation file, flipped live
  through the pointer (:mod:`vmn_exp.core.sqlite_files`); the corrupt one is
  removed once no connection holds it.
- Each use first checks the pointer, so a store follows another process's
  rebuild.
- Each open removes the files a flip left behind that nothing holds any
  more (:func:`vmn_exp.core.sqlite_files.sweep`), and a WAL grown past its
  limit is checkpointed after the write that grew it (:meth:`tidy_wal`).

Each kind of trouble with a file is a warning once per process (it names the
file and the reason), then debug.
"""
import logging
import math
import sqlite3
import time

from vmn_exp.core import sqlite_files
from vmn_exp.core.best_effort import warn_once
from vmn_exp.core.index_store_schema import RecordsOutdated, SchemaTooNew
from vmn_exp.core.index_store_upgrade import regenerate
from vmn_exp.core.sqlite_conn import checkpoint, wal_oversized

FIRST_BACKOFF_SEC = 1.0
MAX_BACKOFF_SEC = 60.0
_monotonic = time.monotonic
_LOGGER = logging.getLogger(__name__)


class StoreConnection:
    """*path*'s connection, opened through *connect_file(file)*."""

    def __init__(self, path, connect_file):
        self.path = path
        self._connect = connect_file
        self.conn = None
        self.file = None
        self._stamp = None
        self._retry_at = None  # math.inf: a newer schema owns the file
        self._backoff = FIRST_BACKOFF_SEC

    def get(self):
        """The live connection, or None while unavailable."""
        if self.path is None:
            return None
        if self.conn is not None and sqlite_files.pointer_stamp(self.path) == self._stamp:
            return self.conn
        if self.conn is None and self._retry_at is not None and _monotonic() < self._retry_at:
            return None
        self.close()
        self._open()
        return self.conn

    def _open(self):
        stamp = sqlite_files.pointer_stamp(self.path)
        file = sqlite_files.live_path(self.path)
        try:
            conn = self._connect(file)
        except SchemaTooNew as exc:
            self._retry_at = math.inf
            warn_once((file, "schema"), f"Experiment index {file} was written by a newer "
                      f"vmn-exp (schema {exc}); this process runs without it")
        except RecordsOutdated as exc:
            self._regenerate(file, exc)
        except (sqlite3.Error, OSError) as exc:
            if type(exc) is sqlite3.DatabaseError:
                self.recover(exc)
            else:
                self._failed(file, exc)
        else:
            self._opened(conn, file, stamp)
            sqlite_files.sweep(self.path)

    def _opened(self, conn, file, stamp):
        self.conn, self.file, self._stamp = conn, file, stamp
        self._retry_at, self._backoff = None, FIRST_BACKOFF_SEC

    def _regenerate(self, file, outdated):
        """*file* holds older records: continue in a new generation beside it."""
        if not sqlite_files.is_file_path(self.path):
            self._failed(file, outdated)
            return
        try:
            conn, fresh = regenerate(self.path, file, outdated.found, self._connect)
        except (sqlite3.Error, OSError, SchemaTooNew, RecordsOutdated) as exc:
            self._failed(file, exc)
            return
        warn_once((file, "records"), f"Experiment index {file} holds records of an older "
                  f"vmn-exp ({outdated}); continuing in {fresh}")
        self._opened(conn, fresh, sqlite_files.pointer_stamp(self.path))
        sqlite_files.sweep(self.path)

    def _failed(self, file, exc):
        self.conn = None
        self._retry_at = _monotonic() + self._backoff
        self._backoff = min(self._backoff * 2, MAX_BACKOFF_SEC)
        warn_once((file, "open"), f"Experiment index {file} unavailable ({exc}); "
                  "running without it, retrying later")

    def on_error(self, exc, warning=None):
        """Triage a failed query: a corrupt file is recovered; anything else
        is *warning* (a template of ``{file}``/``{exc}``; once per file), or
        debug."""
        if type(exc) is sqlite3.DatabaseError:
            self.recover(exc)
        elif warning:
            warn_once((self.file, "query"), warning.format(file=self.file, exc=exc))
        _LOGGER.debug("Experiment index query failed", exc_info=True)

    def recover(self, reason):
        """The live file is corrupt: build an empty one beside it and flip
        the pointer to it. A file opened through no pointer
        (``:memory:``) just reconnects."""
        bad = self.file or sqlite_files.live_path(self.path)
        self.close()
        if not sqlite_files.is_file_path(self.path):
            self._open()
            return
        try:
            fresh = sqlite_files.new_generation(self.path)
            conn = self._connect(fresh)
            sqlite_files.flip(self.path, fresh)
        except (sqlite3.Error, OSError, SchemaTooNew, RecordsOutdated) as exc:
            self._failed(bad, exc)
            return
        warn_once((bad, "corrupt"), f"Experiment index {bad} is unreadable ({reason}); "
                  f"rebuilding it as {fresh}")
        self._opened(conn, fresh, sqlite_files.pointer_stamp(self.path))
        sqlite_files.sweep(self.path)

    def tidy_wal(self):
        """Checkpoint the WAL when it grew past its limit; best-effort: a
        busy one stays oversized, so the next write tries again."""
        if self.conn is not None and wal_oversized(self.file):
            checkpoint(self.conn)

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass
            self.conn = None

    def __del__(self):
        # A sqlite3 connection is in a cycle with its own statement cache
        # (CPython >= 3.11): unclosed, it holds the file until a collection.
        self.close()
