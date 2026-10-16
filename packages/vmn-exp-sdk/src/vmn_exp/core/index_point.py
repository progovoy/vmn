#!/usr/bin/env python3
"""Point reads of one run through the persisted index (plan 25 §2): what
``show -v``/``get_run``/restore/export/``goto`` need to resolve and place a run
without a snapshot of the app.

:func:`point_view` answers a :class:`PointView` over the app's persisted
``exp_rows`` once the persisted index knows every record the storage lists:
records created since it was last refreshed are read and persisted first
(their files only), and records gone from the listing are forgotten — so
references and parent/child links are as current as a refresh would make
them. A run edited in place since (a note, a new metric) keeps its persisted
row until the next refresh; the callers read the run itself from storage.
The records' names are listed (no stat per record) unless the storage's
``record_names_sig`` — a local app directory's settled mtime — held still
since a point read that found every name persisted: then none came or went.

An app the index never saved, a storage that cannot list record names or an
unavailable database answer None: the caller builds the index instead (which
persists it, so the next call is a point read).
"""
import os
import threading

from vmn_exp.core import sqlite_files
from vmn_exp.core.index_listing import METADATA_FILE, as_sigs
from vmn_exp.core.index_record import refresh_record, update_record
from vmn_exp.core.index_store import IndexStore

_STORES = {}  # cache path -> (its store, the file's inode): the process's one per file
_SIG_SCOPE, _SIG_FORMAT = "record-names:", "record-names-sig-1"
_STORES_LOCK = threading.Lock()


def index_path(storage, app_name):
    """Where *storage* persists *app_name*'s index, or None."""
    path_of = getattr(storage, "index_cache_path", None)
    return path_of(app_name) if path_of else None


def shared_store(path):
    """The process's store of the index file at *path* (what the process
    index, point reads, listings and similar searches all read through); a
    file removed and created again gets a new one. A path that names no file
    (None, ``:memory:``) gets a store of its own."""
    if not sqlite_files.is_file_path(path):
        return IndexStore(path)
    with _STORES_LOCK:
        store, inode = _STORES.get(path, (None, None))
        if store is None or _inode(path) != inode:
            store = IndexStore(path)
            _STORES[path] = (store, _inode(path))
        return store


def _inode(path):
    try:
        return os.stat(sqlite_files.live_path(path)).st_ino
    except OSError:
        return None


def point_view(storage, app_name, sync=True):
    """A :class:`PointView` of *app_name*'s runs, or None (see the module);
    *sync* False: the caller just brought the persisted index up to date."""
    path = index_path(storage, app_name)
    if not path:
        return None
    store = shared_store(path)
    if not store.generation(app_name) or (sync and not _sync(storage, app_name, store)):
        return None
    return PointView(store, app_name, fallback=lambda: _snapshot_of(storage, app_name))


def _snapshot_of(storage, app_name):
    from vmn_exp.core.refs import placement_snapshot  # refs builds on this module

    return placement_snapshot(storage, app_name)


def _sync(storage, app_name, store):
    """Persist the records the storage lists that *store* does not know, and
    forget the ones it no longer lists; False when that cannot be told. When
    no record came or went since the last sync (the storage's
    ``record_names_sig`` held still), nothing is listed."""
    sig_of = getattr(storage, "record_names_sig", None)
    sig = sig_of(app_name) if sig_of else None
    if sig is not None and store.kv_get(_SIG_SCOPE + app_name, _SIG_FORMAT) == sig:
        return True
    names = record_keys(storage, app_name)
    diff = store.diff_keys(app_name, names) if names is not None else None
    if diff is None:
        return False
    new, gone = diff
    listed = storage.list_files(app_name, keys=new) if new else {}
    direct_files = getattr(storage, "direct_files", None)
    direct = direct_files() if direct_files else storage
    records = {
        key: _read(storage, direct, app_name, key, files)
        for key, files in listed.items()
        if METADATA_FILE in files
    }
    if (records or gone) and store.save(app_name, records, gone, records) is False:
        return False
    if sig is not None and len(records) == len(new):  # every name is a persisted run
        store.kv_put(_SIG_SCOPE + app_name, _SIG_FORMAT, sig)
    return True


def record_keys(storage, app_name):
    """The record names *storage* lists for *app_name* — without signing each
    record when the backend can say (``list_record_keys``) — or None."""
    keys_of = getattr(storage, "list_record_keys", None)
    if keys_of is not None:
        return keys_of(app_name)
    names_of = getattr(storage, "list_record_names", None)
    return as_sigs(names_of(app_name)) if names_of else None


def _read(storage, direct, app_name, key, files):
    update = lambda *args: update_record(storage, direct, app_name, *args)  # noqa: E731
    return refresh_record(key, files, None, update)[0]


class PointView:
    """The persisted placement of an app's runs, read one query at a time
    (each answer kept for the view's short life): the parts of
    :class:`~vmn_exp.core.index_snapshot.IndexSnapshot` that resolving and
    placing one run use."""

    def __init__(self, store, app_name, fallback=None):
        self._store, self.app_name, self._fallback = store, app_name, fallback
        self.parent_of = _Lookup(lambda v: store.parent_of(app_name, v))
        self.children_of = _Lookup(lambda v: store.children_of(app_name, v) or None)
        # row(verstr): its persisted lean row (``idx`` set), or None. Shared: copy to change.
        self.row = _Lookup(lambda v: store.lean_row_of(app_name, v)).get

    def resolve(self, ref, latest=False, kind="experiment"):
        """``(verstr, error)`` like :meth:`IndexSnapshot.resolve`; when the
        database went away under us, *fallback*'s snapshot answers."""
        answer = self._store.resolve_one(self.app_name, ref, latest, kind)
        if answer is None:
            if self._fallback is None:
                raise RuntimeError("experiment index unavailable")
            return self._fallback().resolve(ref, latest=latest, kind=kind)
        return answer


class _Lookup:
    """A read-only mapping's ``get`` over a per-key query."""

    def __init__(self, query):
        self._query, self._known = query, {}

    def get(self, key, default=None):
        if key not in self._known:
            self._known[key] = self._query(key)
        value = self._known[key]
        return default if value is None else value
