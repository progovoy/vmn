#!/usr/bin/env python3
"""Where ``vmn-exp ui`` searches similar runs (plan 24), per workspace app.

An app whose experiment index persists in a SQLite file (a git workspace
with ``<data_dir>/index``, a store workspace's SQLite cache) is searched in
that file: every save of the index files its runs. Any other — a store
cached in Postgres, ``--no-index`` — gets a host-local database of its own
(``<data_dir>/index/similar/``, or ``:memory:`` without a data dir) kept in
step with the app's snapshots by a
:class:`~vmn_exp.core.similar_filing.SnapshotFiler`: on every refresh of its
index (the refresher's ``on_index_refresh``, :meth:`SimilarCorpora.refreshed`)
and, when a request finds it behind its snapshot, on a background thread
the request waits for up to its deadline (then
:class:`~vmn_exp.core.similar.SimilarDeadlineExceeded`, the sync going on).
Which index serves which app is noted by :meth:`SimilarCorpora.scoped`'s
refresher, as the server asks it for snapshots.
"""
import hashlib
import logging
import os
import threading
import time

from vmn_exp.core import similar_fts, sqlite_files
from vmn_exp.core.similar import SimilarDeadlineExceeded
from vmn_exp.core.similar_corpus import Scope, file_scope
from vmn_exp.core.similar_filing import SnapshotFiler
from vmn_exp.core.similar_rows import SnapshotRows
from vmn_exp.core.sqlite_conn import connect

_LOGGER = logging.getLogger(__name__)


def index_file(index):
    """The SQLite file *index* persists in, or None."""
    path = getattr(index, "path", None)
    return path if sqlite_files.is_file_path(path) else None


class _Corpus:
    """A host-local database and the sync bringing it to the latest snapshot."""

    def __init__(self, conn, app):
        self.filer = SnapshotFiler(conn, app)
        self.lock = threading.Lock()  # the connection: a sync, or a query
        self.cond = threading.Condition()
        self.wanted, self.syncing = None, False

    def synced_to(self, snapshot):
        return self.filer.synced_to(snapshot)

    def sync(self, snapshot):
        with self.lock:
            self.filer.sync(snapshot)
        with self.cond:
            self.cond.notify_all()


def _start(corpus, snapshot):
    """Sync *corpus* to *snapshot* on a thread of its own (one at a time; a
    thread under way takes the latest snapshot asked for next)."""
    with corpus.cond:
        corpus.wanted = snapshot
        if corpus.syncing:
            return
        corpus.syncing = True
    threading.Thread(target=_run, args=(corpus,), name="vmn-similar-sync", daemon=True).start()


def _run(corpus):
    while True:
        with corpus.cond:
            snapshot, corpus.wanted = corpus.wanted, None
            if snapshot is None:
                corpus.syncing = False
                corpus.cond.notify_all()
                return
        try:
            corpus.sync(snapshot)
        except Exception:
            _LOGGER.warning("Filing similar-runs documents failed", exc_info=True)


class _Scoped:
    """*refresher*, noting each index it is asked about as *key*'s."""

    def __init__(self, refresher, corpora, key, app):
        self._refresher, self._corpora, self._key, self._app = refresher, corpora, key, app

    def __getattr__(self, name):
        return getattr(self._refresher, name)

    def snapshot(self, index, journal=None):
        self._corpora.note(index, self._key, self._app)
        if journal is None:
            return self._refresher.snapshot(index)
        return self._refresher.snapshot(index, journal)


class SimilarCorpora:
    def __init__(self, db_dir=None):
        self._db_dir = db_dir
        self._indexes = {}  # key -> the index serving it
        self._keys = {}  # index -> (key, app)
        self._corpora = {}  # key -> _Corpus
        self._lock = threading.Lock()

    def scoped(self, refresher, ws_name, app_name):
        return _Scoped(refresher, self, (ws_name, app_name), app_name)

    def note(self, index, key, app):
        with self._lock:
            self._indexes[key], self._keys[index] = index, (key, app)

    def refreshed(self, index, snapshot):
        """*index* was refreshed to *snapshot*: sync its app's database."""
        with self._lock:
            found = self._keys.get(index)
        if found is None or index_file(index):
            return
        try:
            self._corpus(*found).sync(snapshot)
        except Exception:
            _LOGGER.warning("Filing similar-runs documents failed", exc_info=True)

    def _corpus(self, key, app):
        with self._lock:
            corpus = self._corpora.get(key)
            if corpus is None:
                corpus = self._corpora[key] = _Corpus(self._connect(key), app)
            return corpus

    def _connect(self, key):
        similar_fts.require_fts5()
        path = ":memory:"
        if self._db_dir:
            folder = os.path.join(self._db_dir, "similar")
            os.makedirs(folder, exist_ok=True)
            name = hashlib.sha256(repr(key).encode()).hexdigest()[:16]
            path = os.path.join(folder, f"{name}.sqlite")
        conn = connect(path)
        similar_fts.ensure_tables(conn)
        return conn

    def scope(self, key, app_name, snapshot, schema=None, deadline=None):
        """The :class:`~vmn_exp.core.similar_corpus.Scope` of *key*'s app at
        *snapshot* (labelled *key*). Close it once done."""
        with self._lock:
            path = index_file(self._indexes.get(key))
        if path:
            scope = file_scope(app_name, path, schema, snapshot)
            if scope is not None:
                scope.label = key
                return scope
        corpus = self._corpus(key, app_name)
        if not corpus.synced_to(snapshot):
            _start(corpus, snapshot)
            with corpus.cond:
                left = None if deadline is None else deadline - time.monotonic()
                # Synced to it, or done (to a later snapshot another request asked for).
                if not corpus.cond.wait_for(
                        lambda: corpus.synced_to(snapshot) or not corpus.syncing, left):
                    raise SimilarDeadlineExceeded
        return Scope(corpus.filer.app, corpus.filer.conn, SnapshotRows(snapshot), schema,
                     corpus.lock, label=key)
