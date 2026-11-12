#!/usr/bin/env python3
"""An incremental index of an app's experiments: leaderboard rows without
re-reading every log whenever anything changes.

This module is the facade: :class:`ExperimentIndex` is assembled from mixins
that keep all state on the index — :mod:`~vmn_exp.core.index_surface`
(properties, freshness, snapshots), :mod:`~vmn_exp.core.index_refresh`
(refreshing, how a refresh decides what to read), :mod:`~vmn_exp.core.index_load`
(loading what a listing hands over), :mod:`~vmn_exp.core.index_publish`
(applying and publishing changes), :mod:`~vmn_exp.core.index_persist`
(its store) and :mod:`~vmn_exp.core.index_read` (reading records) — and
:mod:`~vmn_exp.core.index_direct` builds snapshots without it. What tests
patch here (the chunk size, the retry interval, the record readers, the
process-wide registry) is read here, the moved code reaching it through seam
methods such as ``_chunk()``.

Storage is duck-typed (``list_files``, ``load_file``, and optionally
``list_record_names``/``list_files(keys=)``/``direct_files``/``read_file_from``/
``plain_record_dir``/``index_cache_path``/``cache_identity``); like the rest of
``core`` this imports nothing from ``cli``, ``ui`` or ``exp``.
"""
import logging
import threading

from vmn_exp.core.fold import fold_row
from vmn_exp.core import index_freshness
from vmn_exp.core.index_baseline import ListingBaseline
from vmn_exp.core.index_bulk import BulkPublish
from vmn_exp.core.index_direct import (  # noqa: F401  (importers' names)
    _direct_folds,
    _run_states,
    direct_snapshot,
    snapshot_of_folds,
)
from vmn_exp.core.index_first_rows import first_rows, first_rows_of, kept_parts
from vmn_exp.core.index_io_process import IOProcessError  # noqa: F401
from vmn_exp.core.index_journal_mark import JournalMark
from vmn_exp.core.index_load import BEHIND_REFRESH_SEC, MIGRATING_PUBLISH_SEC, IndexLoad  # noqa: F401
from vmn_exp.core.index_pending import PendingSave
from vmn_exp.core.index_point import index_path, shared_store
from vmn_exp.core.index_record import refresh_record, update_record
from vmn_exp.core.index_unreadable import Unreadable
from vmn_exp.core.index_vmx_check import VmxCheck
from vmn_exp.core.index_persist import IndexPersist
from vmn_exp.core.index_lean_store import sort_timestamp as _timestamp
from vmn_exp.core.index_publish import _BISECT_NEW, IndexPublish  # noqa: F401
from vmn_exp.core.index_read import IndexRead
from vmn_exp.core.index_refresh import IndexRefresh
from vmn_exp.core.index_rows import row_copies as _row_copies
from vmn_exp.core.index_snapshot import IndexSnapshot, RowCache  # noqa: F401  (importers' name)
from vmn_exp.core.index_store import IndexStore
from vmn_exp.core.index_surface import FIRST_SNAPSHOT_WAIT_SEC, IndexSurface  # noqa: F401
from vmn_exp.core.index_sweep import DEFAULT_FULL_SWEEP_SEC, Sweep
from vmn_exp.core.index_load_pool import LoadPool
from vmn_exp.core.log import load_log
from vmn_exp.core.ports import wall_seconds
from vmn_exp.core.real_io import real_io
from vmn_exp.core.status import load_run_state
from vmn_exp.core.traced_lock import TracedLock

_LOGGER = logging.getLogger(__name__)
# Records a remote backend re-reads at once (each costs a few round trips;
# on a free-threaded build no more than the cores: index_load_pool).
_REMOTE_WORKERS = 32
# Records a remote backend reads between persisting what it has (and, while
# the index is small, publishing it: see index_bulk).
_REMOTE_CHUNK = 500
# The newest persisted rows a warm restart serves before reading back the rest.
FIRST_ROWS = 500
FIRST_ROWS_MAX = 2000  # with their ancestors and the newest outer runs
# A record a refresh could not read is read again this long after (doubling).
RETRY_UNREADABLE_SEC = 60.0


class ExperimentIndex(IndexSurface, IndexRefresh, IndexLoad, IndexPublish, IndexPersist, IndexRead):
    """Incrementally maintained rows for one app of one storage backend.

    *clock* (a :class:`~vmn_exp.core.ports.Clock`) times its refreshes,
    sweeps, freshness and store (None: ``real_io().clock``)."""

    def __init__(
        self, storage, app_name, cache_path=None, full_sweep_sec=DEFAULT_FULL_SWEEP_SEC,
        cache_store=None, *, clock=None,
    ):
        self.clock = self._clock = clock = clock or real_io().clock
        self._storage = storage
        self.app_name = app_name
        self._cache_path = cache_path
        self._store = cache_store or IndexStore(cache_path, clock=clock)
        self._unsaved = PendingSave()  # what a failed save left to persist
        self._freshness = index_freshness.Freshness(
            lambda: self._io or self._store, app_name,
            wall_seconds(clock))
        self._sweep = Sweep(storage, app_name, full_sweep_sec, clock=clock)
        self._baseline = ListingBaseline(self._store, app_name)
        self._mark = JournalMark(self._store, app_name)
        self._io = None  # the I/O helper process, once use_io_process() started it
        self._records = None
        self._order = None  # record keys in storage order
        self._stamps = None  # their timestamps, for bisecting new keys in
        self._reorder = ((), False)  # (new keys, whether one was re-described)
        self._rows = RowCache()
        self._bulk = BulkPublish(clock.monotonic)
        self._snapshot = None
        self._placeholder = None  # (expected, the empty snapshot saying so)
        self._first_rows = None  # a warm restart's newest rows, until its snapshot (snapshot_now)
        self._kept = None  # the rows an upgrade kept, while it re-derives them (_derive_first)
        self._loaders = None  # a bulk load's worker processes (index_remote_workers)
        self._pool = LoadPool(_REMOTE_WORKERS, "vmn-index-load")  # kept across a bulk load's chunks
        self._rests = set()  # records a bulk load read rows-first, the rest to read
        self._unreadable = Unreadable(app_name, self._monotonic)
        self._vmx = VmxCheck(lambda: self._io or self._store, app_name,
                             clock=clock.monotonic)  # an upgrade's check
        self._io_unreadable = None  # the I/O helper's Unreadable.summary(), after its refresh
        self._lock = TracedLock(f"index refresh:{app_name}")
        self._published = threading.Event()  # a first snapshot, or a refresh that failed
        self._servable = threading.Event()  # that, or the first rows (snapshot_now)
        self._revalidator = None  # the thread a warm snapshot() started
        self._revalidator_lock = threading.Lock()
        self.generation = 0
        self.last_refresh_at = None  # monotonic start of the last refresh
        self.published_at = None  # monotonic time the current snapshot was built
        self._cache_gen = None  # a follower's CacheStore generation; None for a leader
        self._lean = False  # see sync()
        self._lean_index = None  # the lean copy sync() refreshes while this one is unloaded
        self._unread = 0  # new records a chunked refresh has yet to read
        self._cold = False  # records loaded whole, their folds held until saved (_drop_folds)
        self.drops_folds = True  # False: whoever adopts this index drops them (a rebuild)

    def _monotonic(self):
        return self._clock.monotonic()

    # -- seams: the module globals tests patch, read at call time ------------

    def _chunk(self):
        return _REMOTE_CHUNK

    def _retry_sec(self):
        return RETRY_UNREADABLE_SEC

    def _sort_stamp(self):
        return _timestamp

    def _kept_parts(self):
        return kept_parts(self._store, self.app_name)

    @classmethod
    def follower(cls, cache_store, scope, *, clock=None):
        """An index that never reads storage: each refresh applies
        *cache_store*'s ``load_since`` deltas, which a leader saves."""
        index = cls(None, scope, clock=clock)
        index._store = cache_store
        index._cache_gen = 0
        return index

    def _lean_copy(self):
        lean = ExperimentIndex(self._storage, self.app_name, self._cache_path,
                               self.full_sweep_sec, self._store, clock=self._clock)
        lean._lean = True
        return lean

    def _newest_rows(self):
        if self._io is not None:  # the helper owns the files
            return first_rows_of(self.app_name, self._io.first_rows(FIRST_ROWS, FIRST_ROWS_MAX))
        return first_rows(self._store, self.app_name, FIRST_ROWS, FIRST_ROWS_MAX)

    def _refresh_one(self, key, names, record, direct):
        """:func:`refresh_record` of one record; one that fails is set aside
        (:mod:`~vmn_exp.core.index_unreadable`), never the refresh, and read
        afresh when retried (a failure may have left it half updated), not
        before its retry is due."""
        retried = key in self._unreadable
        if retried and not self._unreadable.is_due(key, RETRY_UNREADABLE_SEC):
            return record, False, False, False
        try:
            result = refresh_record(key, names, None if retried else record,
                                    lambda *a: self._update(*a, direct))
        except Exception as exc:
            self._unreadable.failed(key, exc)
            return record, False, False, False
        if retried:
            self._unreadable.read(key)
        return result

    def _update(self, key, names, record, direct):
        """Refresh one record in place; ``(folded content changed, metadata
        changed, run state changed)``."""
        return update_record(self._storage, direct, self.app_name, key, names, record)


# -- process-wide access with a direct fallback ------------------------------

_SHARED = {}
_SHARED_LOCK = threading.Lock()


def shared_index(storage, app_name, cache_path=None, full_sweep_sec=None, *, clock=None):
    """The process-wide index for *storage*'s *app_name* data.

    Keyed by the backend's ``cache_identity()`` so equivalent storage objects
    share one warm index. Persisted at *cache_path* when given (the ui keeps its
    own under the server data dir), else at the backend's ``index_cache_path``.
    A *full_sweep_sec* other than None sets that index's sweep interval.
    A new index runs on *clock* (see :class:`ExperimentIndex`); the first
    caller's clock is the one a shared index keeps.
    """
    index = _process_index(storage, app_name, cache_path, clock)
    if full_sweep_sec is not None:
        index.full_sweep_sec = full_sweep_sec
    return index


def _process_index(storage, app_name, cache_path, clock=None):
    # The storage's own index file is the one point reads, listings and
    # similar searches read: the process's one store of it. A caller's file
    # (the ui's, one per workspace) keeps a store per index.
    store = None
    if cache_path is None:
        cache_path = index_path(storage, app_name)
        store = shared_store(cache_path) if cache_path else None
    identity_of = getattr(storage, "cache_identity", None)
    identity = identity_of() if identity_of else None
    if identity is None:
        return ExperimentIndex(storage, app_name, cache_path, cache_store=store, clock=clock)
    key = (identity, app_name, cache_path)
    with _SHARED_LOCK:
        index = _SHARED.get(key)
        if index is None:
            index = _SHARED[key] = ExperimentIndex(storage, app_name, cache_path,
                                                   cache_store=store, clock=clock)
        return index


def direct_rows(
    storage,
    app_name,
    with_create_note=False,
    read_log=load_log,
    read_run_state=load_run_state,
    schema=None,
):
    """``(rows, run_states)`` by reading every record — the index's reference.

    *read_log* / *read_run_state* are the caller's loaders; a None
    *read_run_state* skips the run states (``{}``). *schema* is the app's
    metrics schema.
    """
    rows = [
        fold_row(idx, meta, fold, with_create_note, schema)
        for idx, meta, fold in _direct_folds(storage, app_name, read_log)
    ]
    if read_run_state is None:
        return rows, {}
    return rows, _run_states(storage, app_name, rows, read_run_state)


def indexed_snapshot(
    storage,
    app_name,
    cache_path=None,
    max_age_sec=0,
    full_sweep_sec=None,
    wait=False,
    fallback=direct_snapshot,
    schema=None,
    *,
    clock=None,
):
    """The shared index's :class:`IndexSnapshot`, refreshed when older than a
    positive *max_age_sec* (the default 0 takes a loaded index as it is: see
    :meth:`ExperimentIndex.refresh_if_stale`) — or, with *wait*, refreshed now
    even if another thread's refresh has to finish first. *full_sweep_sec* is passed on to
    :func:`shared_index`. Rows follow the metrics *schema* the caller passes
    (:meth:`IndexSnapshot.summarized`), none by default. If the index fails,
    ``fallback(storage, app_name, schema)`` answers instead; a None
    *fallback* returns None. *clock*: see :func:`shared_index`."""
    try:
        index = shared_index(storage, app_name, cache_path, full_sweep_sec, clock=clock)
        snap = index.refresh().snapshot() if wait else index.refresh_if_stale(max_age_sec)
        return snap.summarized(schema)
    except Exception:
        _LOGGER.debug("Experiment index unavailable", exc_info=True)
        return fallback(storage, app_name, schema) if fallback else None


def indexed_status_rows(
    storage, app_name, with_create_note=False, cache_path=None, schema=None, *, clock=None
):
    """``(rows, run_states, observed_at)`` from an up-to-date snapshot — fresh
    row copies (see :meth:`ExperimentIndex.rows`), the run states and
    ``{verstr: run_state.yml store write time}``, the ``observed_at`` a status
    derivation takes. *schema*, *clock*: see :func:`indexed_snapshot`."""
    snap = indexed_snapshot(storage, app_name, cache_path, wait=True, schema=schema, clock=clock)
    return (
        _row_copies(snap, with_create_note),
        dict(snap.run_states),
        dict(snap.run_state_observed_at),
    )
