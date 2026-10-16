#!/usr/bin/env python3
"""Where a similar-runs query searches: a :class:`Scope` — one app's FTS
tables (a connection), its runs (:mod:`vmn_exp.core.similar_rows`) and its
conf metrics schema.

- :func:`file_scope`: the app's persisted index file, whose saves file every
  run (:mod:`vmn_exp.core.similar_filing`); refiled from its lean tables first
  when documents are missing or another profile version filed them.
- :func:`snapshot_scope`: no index file (``VMN_INDEX_CACHE_DIR=none``, a
  hand-built snapshot): a ``:memory:`` database filled from the snapshot,
  kept while the snapshot lives — the same search, only slower to start.
"""
import os
import threading
import weakref
from collections import OrderedDict

from vmn_exp.core import similar_fts, sqlite_files
from vmn_exp.core.similar_filing import SnapshotFiler, file_lean
from vmn_exp.core.similar_rows import SnapshotRows, StoreRows
from vmn_exp.core.sqlite_conn import connect, write_tx

_APP = object()  # a scope's label defaults to its app


class Scope:
    """One app's search inputs: its documents are filed under *app* in *conn*
    (*lock* serializes its use); its results carry *label* (default *app*)."""

    def __init__(self, app, conn, rows, schema=None, lock=None, label=_APP, cache_key=None):
        self.app, self.conn, self.rows, self.schema = app, conn, rows, schema or {}
        self.lock = lock or threading.Lock()
        self.label = app if label is _APP else label
        # What the documents are at (None: unknown): equal keys, equal rankings.
        self.cache_key = cache_key


def memory_conn(path=":memory:"):
    conn = connect(path)
    similar_fts.ensure_tables(conn)
    return conn


_MEMORY = weakref.WeakKeyDictionary()  # snapshot -> (filer, lock)
_MEMORY_APP = ""  # the app a memory database files its one app's runs under
_MEMORY_LOCK = threading.Lock()


def snapshot_scope(app, snapshot, schema=None):
    """A :class:`Scope` of *snapshot* (results labelled *app*) over its own
    ``:memory:`` database."""
    similar_fts.require_fts5()
    with _MEMORY_LOCK:
        if snapshot not in _MEMORY:
            _MEMORY[snapshot] = (SnapshotFiler(memory_conn(), _MEMORY_APP), threading.Lock())
        filer, lock = _MEMORY[snapshot]
    with lock:
        filer.sync(snapshot)
        key = ("memory", filer.token, filer.syncs)
    return Scope(_MEMORY_APP, filer.conn, SnapshotRows(snapshot), schema, lock, label=app,
                 cache_key=key)


_POOL = OrderedDict()  # logical path -> (live file, connection, lock): its cache stays warm
_POOL_SIZE = 8
_POOL_LOCK = threading.Lock()


def _close(conn, lock):
    if lock.acquire(blocking=False):  # in use: left to the garbage collector
        conn.close()


def _pooled(path, file):
    """The process's connection to the index at *path* (now in *file*: its
    name and inode) and its lock: opened once, reopened once a rebuild
    flipped the file (at most
    :data:`_POOL_SIZE` kept, the least recently used closed)."""
    with _POOL_LOCK:
        found = _POOL.get(path)
        if found is not None and found[0] == file:
            _POOL.move_to_end(path)
            return found[1:]
    conn = connect(file[0])
    conn.execute("PRAGMA mmap_size=0")  # pages read into the cache, not the RSS
    with _POOL_LOCK:
        old = _POOL.pop(path, None)
        if old is not None:
            _close(*old[1:])
        _POOL[path] = (file, conn, threading.Lock())
        while len(_POOL) > _POOL_SIZE:
            _close(*_POOL.popitem(last=False)[1][1:])
        return _POOL[path][1:]


def open_file(path):
    """``(connection, lock, (live file, inode))`` of the index file at *path*
    when it holds the similar tables, else None."""
    similar_fts.require_fts5()
    if not sqlite_files.is_file_path(path):
        return None
    file = sqlite_files.live_path(path)
    try:
        # The inode too: a file removed and created again is another database.
        file = (file, os.stat(file).st_ino)
        conn, lock = _pooled(path, file)
        with lock:
            found = similar_fts.has_tables(conn)
    except Exception:
        return None
    return (conn, lock, file) if found else None


def _generation(conn, app):
    found = conn.execute("SELECT gen FROM exp_index_gen WHERE app = ?", (app,)).fetchone()
    return found[0] if found else 0


def repaired(conn, app):
    """Refile *app* from the lean tables when its documents fall short of its
    runs or another profile version filed some."""
    (runs,) = conn.execute("SELECT COUNT(*) FROM exp_rows WHERE app = ?", (app,)).fetchone()
    if runs == similar_fts.doc_count(conn, app) and not similar_fts.stale_count(conn, app):
        return
    with write_tx(conn):
        file_lean(conn, app)


_CHECKED = OrderedDict()  # (file, app, generation) already checked by repaired()


def file_scope(app, path, schema=None, snapshot=None, repair=True):
    """A :class:`Scope` over the index file at *path* (rows read from
    *snapshot* when given, else point reads on the file), :func:`repaired`
    first unless *repair* is False (once per index generation); None
    without one."""
    opened = open_file(path)
    if opened is None:
        return None
    conn, lock, file = opened
    with lock:
        key = (file, app, _generation(conn, app))
        if repair and key not in _CHECKED:
            repaired(conn, app)
            key = (file, app, _generation(conn, app))
            _CHECKED[key] = None
            while len(_CHECKED) > 64:
                _CHECKED.popitem(last=False)
    rows = SnapshotRows(snapshot) if snapshot is not None else StoreRows(conn, app)
    return Scope(app, conn, rows, schema, lock, cache_key=key)


def as_scope(scope):
    """*scope* — a :class:`Scope`, or ``(app, snapshot or Scope, schema)``."""
    if isinstance(scope, Scope):
        return scope
    label, source, schema = scope
    if isinstance(source, Scope):
        return source
    return snapshot_scope(label, source, schema)
