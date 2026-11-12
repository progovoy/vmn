#!/usr/bin/env python3
"""An incremental index of an app's experiments: leaderboard rows without
re-reading every log whenever anything changes.

Which records a refresh looks at is :mod:`experiment_index_sweep`'s call: the
new, changed, live and recently changed ones from a names-only listing, and
all of them every ``full_sweep_sec`` (300 s, across processes: the listing
baselines persist beside the records, :mod:`experiment_index_baseline`). Of those only what moved is read: a new record
is loaded, a changed ``metadata.yml`` re-read, a grown log read from where it
was last read up to (:mod:`experiment_index_logs`), a rewritten
``run_state.yml`` — a heartbeat — re-read on its own. The folded state
persists in SQLite (:mod:`experiment_index_store`), so a new process starts
warm; a heartbeat there rewrites only its small run-state row. A restarted
server's first :meth:`ExperimentIndex.snapshot` serves those persisted rows
as soon as they are read and revalidates them against the storage listing in
the background (seconds at 100k records); :meth:`refresh_if_stale` and
:meth:`refresh` still answer only once storage was listed. Reading them
back is O(runs) (minutes at ~700k on a server): meanwhile
:meth:`~ExperimentIndex.snapshot_now` serves the newest ``FIRST_ROWS``
(:mod:`experiment_index_first_rows`).

Readers get an immutable :class:`IndexSnapshot` per ``generation`` (bumped by
anything visible, run states included) that never takes the index lock or
touches storage. Its rows are ``experiment_row``'s under no metrics schema and
without ``metric_summary`` or ``outputs`` (the snapshot keeps them per
verstr; the row copies handed out carry them) — nor the run's
``features``/``intent``/hypothesis, which only the snapshot keeps; a caller's
schema is a view of it (:meth:`IndexSnapshot.summarized`), never index state.
Status is derived from its run states on every read, since it depends on the
clock.

A cold build's many new local records load in worker processes
(:mod:`experiment_index_workers`), when the direct files expose
``plain_record_dir``. A server refreshing under load moves all of it —
listings, reads, persistence — to a helper process with
:meth:`ExperimentIndex.use_io_process` (:mod:`experiment_index_io_process`):
each filesystem call hands the GIL to a busy request thread and waits up to a
switch interval to get it back, which at 100k records made one refresh take
minutes. A refresh then costs O(what changed) in the index's process.

A journaled index (the ui's, hinted by a store's change journal) persists its
journal mark with its records (:mod:`experiment_index_journal_mark`), so a
restart replays the journal from there instead of listing every record; on a
remote store its full listings run behind serving, a chunk applied per
refresh (:mod:`experiment_index_sweep_behind`). :meth:`freshness` says
which of these it is busy with, between refreshes too.

This module is the facade: :class:`ExperimentIndex` is assembled from mixins
that keep all state on the index — :mod:`~vmn_exp.core.index_surface`
(properties, freshness, snapshots), :mod:`~vmn_exp.core.index_publish`
(applying and publishing changes), :mod:`~vmn_exp.core.index_persist`
(its store) and :mod:`~vmn_exp.core.index_read` (reading records) — and :mod:`~vmn_exp.core.index_direct`
builds snapshots without it. What tests patch here (the chunk size, the
retry interval, the record readers, the process-wide registry) is read here,
the moved code reaching it through seam methods such as ``_chunk()``.

Storage is duck-typed (``list_files``, ``load_file``, and optionally
``list_record_names``/``list_files(keys=)``/``direct_files``/``read_file_from``/
``plain_record_dir``/``index_cache_path``/``cache_identity``); like the rest of
``core`` this imports nothing from ``cli``, ``ui`` or ``exp``.
"""
import bisect
import logging
import threading
from contextlib import nullcontext
from dataclasses import replace

from vmn_exp.core.fold import fold_row
from vmn_exp.core.gc_pause import gc_paused
from vmn_exp.core import index_freshness
from vmn_exp.core.index_baseline import ListingBaseline
from vmn_exp.core.index_bulk import BulkPublish, loading_snapshot
from vmn_exp.core.index_direct import (  # noqa: F401  (importers' names)
    _direct_folds,
    _run_states,
    direct_snapshot,
    snapshot_of_folds,
)
from vmn_exp.core.index_first_rows import first_rows, first_rows_of, kept_parts, kept_snapshot
from vmn_exp.core.index_io_process import IOProcessError, start_io_process  # noqa: F401
from vmn_exp.core.index_journal_mark import JournalMark
from vmn_exp.core.index_load_queue import LoadQueue
from vmn_exp.core.index_rows_first import first_objects
from vmn_exp.core.index_listing import ListingWatch
from vmn_exp.core.index_pending import PendingSave
from vmn_exp.core.index_point import index_path, shared_store
from vmn_exp.core.index_record import refresh_record, update_record
from vmn_exp.core.index_reread import hint_unloaded
from vmn_exp.core.index_unreadable import Unreadable
from vmn_exp.core.index_vmx_check import VmxCheck
from vmn_exp.core.index_persist import IndexPersist
from vmn_exp.core.index_lean_store import sort_timestamp as _timestamp
from vmn_exp.core.index_publish import IndexPublish
from vmn_exp.core.index_read import IndexRead
from vmn_exp.core.index_rows import row_copies as _row_copies
from vmn_exp.core.index_snapshot import IndexSnapshot, RowCache  # noqa: F401  (importers' name)
from vmn_exp.core.index_store import IndexStore
from vmn_exp.core.index_surface import FIRST_SNAPSHOT_WAIT_SEC, IndexSurface  # noqa: F401
from vmn_exp.core.index_sweep import (
    DEFAULT_FULL_SWEEP_SEC,
    METADATA_FILE,
    Sweep,
)
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
# How long a refresh of a cold remote index keeps loading what its listing
# behind serving hands over before letting the next refresh serve the
# journal's hints (and the ui see the refresh end, not a stuck one).
BEHIND_REFRESH_SEC = 30.0
# The newest persisted rows a warm restart serves before reading back the rest.
FIRST_ROWS = 500
FIRST_ROWS_MAX = 2000  # with their ancestors and the newest outer runs
_BISECT_NEW = 64  # new records past which the order is merged, not inserted into
# Seconds between the empty snapshots a re-derive publishes its progress in.
MIGRATING_PUBLISH_SEC = 1.0
# A record a refresh could not read is read again this long after (doubling).
RETRY_UNREADABLE_SEC = 60.0


def _listed_at(work_item):
    """When the listing saw *work_item*'s metadata.yml written (a remote
    backend's ``(size, mtime, etag)`` signature), 0 when it does not say."""
    sig = work_item[1].get(METADATA_FILE)
    return sig[1] if isinstance(sig, (list, tuple)) and len(sig) > 1 else 0


class ExperimentIndex(IndexSurface, IndexPublish, IndexPersist, IndexRead):
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

    def _sorted_keys(self):
        """Record keys in storage order (by timestamp, then key — the order
        the persisted ``exp_rows`` number, see
        :mod:`vmn_exp.core.index_lean_store`). New records
        are bisected into the current order; a first build, a re-described
        record (its timestamp may have moved) or a removal sorts them all."""
        new, resort = self._reorder
        if self._order is None or resort:
            keys = [k for k, r in self._records.items() if r["meta"] is not None]
            self._stamps = sorted((_timestamp(self._records[k]["meta"]), k) for k in keys)
            return [key for _, key in self._stamps]
        stamps = [(_timestamp(meta), key) for key in new
                  for meta in (self._records[key]["meta"],) if meta is not None]
        if len(stamps) > _BISECT_NEW:  # one merge of two sorted runs beats that many inserts
            self._stamps = sorted(self._stamps + stamps)
            return [key for _, key in self._stamps]
        order = list(self._order)
        for stamp in stamps:
            at = bisect.bisect_right(self._stamps, stamp)
            self._stamps.insert(at, stamp)
            order.insert(at, stamp[1])
        return order

    @classmethod
    def follower(cls, cache_store, scope, *, clock=None):
        """An index that never reads storage: each refresh applies
        *cache_store*'s ``load_since`` deltas, which a leader saves."""
        index = cls(None, scope, clock=clock)
        index._store = cache_store
        index._cache_gen = 0
        return index

    # -- refresh -------------------------------------------------------------

    def refresh(self):
        """Bring the index up to date with storage; returns self."""
        with self._lock:
            self._refresh_locked()
        return self

    def sync(self):
        """Bring the persisted rows up to date with storage; whether all of
        them are. An index not loaded yet stays so: a *lean* copy refreshes
        them, decoding no record it does not re-read, building no snapshot."""
        with self._lock:
            if self._records is not None or self._io is not None:
                self._lean_index = None
                index = self
            else:
                index = self._lean_index = self._lean_index or self._lean_copy()
        with index._lock:
            index._refresh_locked()
            return not index._unsaved.pending

    def _lean_copy(self):
        lean = ExperimentIndex(self._storage, self.app_name, self._cache_path,
                               self.full_sweep_sec, self._store, clock=self._clock)
        lean._lean = True
        return lean

    def refresh_if_stale(self, max_age_sec):
        """The current snapshot, refreshed first if older than a positive
        *max_age_sec*; 0 (or None) answers it as it is.

        While another thread refreshes, the current snapshot is returned at
        once — only the very first load waits for it (and loads whatever the
        age). A caller that must see every write made before it calls
        :meth:`refresh`.
        """
        snap = self._snapshot
        if snap is None:
            return self._first_load()
        if (max_age_sec or 0) <= 0:
            return snap
        fresh_at = self.last_refresh_at  # None: persisted rows not revalidated yet
        if fresh_at is not None and self._monotonic() - fresh_at < max_age_sec:
            return snap
        if not self._lock.acquire(blocking=False):
            return snap
        try:
            self._refresh_locked()
        finally:
            self._lock.release()
        return self._snapshot

    def _first_load(self):
        with self._lock:
            if self._snapshot is None:
                self._refresh_locked()
            return self._snapshot

    def use_io_process(self):
        """Do this index's filesystem work in a helper process from now on;
        False when the storage is not a plain local store, the index already
        loaded in-process, or no helper could start; also False, at once, while
        a refresh holds the index (it loads in-process: a request asking never
        waits out a cold load). :meth:`close` stops it."""
        if not self._lock.acquire(blocking=False):
            return self._io is not None
        try:
            if self._io is None and self._records is None:
                self._io = start_io_process(self._storage, self.app_name, self._cache_path)
                if self._io is not None:
                    self._sweep.watch = self._io.watch
                    self._freshness.load()  # now: the pipe is the refresh's
            return self._io is not None
        finally:
            self._lock.release()

    def close(self):
        """Stop the I/O helper process, if any; later refreshes run in-process
        from a full listing."""
        with self._lock:
            self._close_loaders()
            self._pool.close()
            if self._io is not None:
                self._io.close()
                self._io = None
                self._sweep.watch = ListingWatch(self._storage, self.app_name)
                self._sweep.reset()

    def adopt(self, other, store=None):
        """Serve *other*'s records (a rebuild of the same app) from now on,
        persisting into *store* (default: *other*'s). Hints not yet listed
        carry over; an I/O helper is stopped (refreshes run in-process)."""
        with self._lock:
            if self._io is not None:
                self._io.close()
                self._io = None
            for key in self._sweep._take_hints():
                other._sweep.hint(key)
            self._records, self._order, self._stamps = other._records, other._order, other._stamps
            self._rows, self._sweep, self._bulk = other._rows, other._sweep, other._bulk
            self._store, self._unsaved = store or other._store, other._unsaved
            self._cold = other._cold  # a rebuild's folds: dropped against this store
            if self._store is not other._store:
                self._baseline = ListingBaseline(self._store, self.app_name)
                self._mark = JournalMark(self._store, self.app_name)
            else:
                self._baseline, self._mark = other._baseline, other._mark
            self.generation += 1
            self._snapshot = self._build_snapshot()

    def _refresh_locked(self):
        started = self._monotonic()
        self._freshness.started()
        if self._cache_gen is not None:
            self._refresh_from_cache()
            self._freshness.reload()  # its leader's
            self.last_refresh_at = started
            return
        for key in self._unreadable.due(RETRY_UNREADABLE_SEC):
            self._sweep.hint(key)
        try:
            with self._paused_unless_remote():
                self._refresh_from_storage(started)
            self._sweep.applied()
            if self._vmx.due():
                self._check_step()
        except Exception:
            self._first_rows = None  # a failed first load: a retry serves them again
            # A listing's changes may have been taken but not applied: list
            # them again — all of them once a dead I/O helper took its
            # baselines along.
            if self._io is not None and not self._io.alive():
                self._sweep.reset()
            else:
                self._sweep.failed()
            raise
        finally:
            self._set_published()
            self._freshness.idle()
        self.last_refresh_at = started
        self._freshness.refreshed()

    def _check_step(self, limit=None):
        """A step of an upgrade's check (:mod:`~vmn_exp.core.index_vmx_check`):
        its failure (a throttled store) is retried at the next step, never
        the refresh's."""
        try:
            return self._vmx.step(self._storage, self._records, self._sweep.hint, limit)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("checking %s's compacted metrics failed; retried", self.app_name,
                            exc_info=True)
            return 0

    def check_vmx(self, limit=None):
        """Run an upgrade's check now (its listing first): *limit* records,
        else all left; how many were checked."""
        if self._vmx.state() is None:
            return 0
        with self._lock:
            self._vmx.list_all()
            state = self._vmx.state()
            if state is None:
                return 0
            return self._check_step(state["total"] - state["done"] if limit is None else limit)

    def _paused_unless_remote(self):
        """A local refresh is bulk work throughout, so collection pauses for
        all of it (see :mod:`~vmn_exp.core.gc_pause`). A remote one pauses it
        only to decode and fold, never across its listing and reads: at 486k
        records on S3 those take hours, and the process's garbage piled up."""
        return nullcontext() if self._remote() else gc_paused()

    def _refresh_from_storage(self, started):
        if self._records is None:
            self._serve_first_rows()
            placeholder = self._derive_first()
            if self._keeps_baseline():  # read before the records it vouches for
                self._baseline.load(self._sweep, started)
            with gc_paused():
                self._records = self._load_records()
                if not self._lean and (placeholder or (
                        self._records and self._snapshot is None)):
                    self._publish_persisted()
            hint_unloaded(self._io or self._store, self.app_name, self._records,
                          self._sweep.hint)
            for key in self._vmx.load():  # what the check found to fold again
                self._sweep.hint(key)
        self._sweep.behind = self._io is None and self._remote()
        self._freshness.listing(self._listing_phase(started), self._records,
                                self._listing_position())
        listing, removed = self._sweep.listing(self._records, started)
        self._unreadable.forget(self._sweep.listed_gone)
        self._load_listed(listing, removed, started)
        while self._more_relisted(started):
            self._load_listed(*self._sweep.next_relisted(self._records, self._monotonic()), started)
        if self._snapshot is None and not self._lean:  # a refresh ends with one
            self._publish_pending()
        if self._rests and self._sweep.relisted_new() is False:
            for key in self._rests:  # what rows-first left unread: listed afresh
                self._sweep.hint(key)
            self._rests = set()
        if self._cold:
            self._drop_folds()

    def _serve_first_rows(self):
        """Before reading the persisted rows back (O(runs)) — or the rows an
        upgrade kept, before re-deriving them (plan 34 §4) — let
        :meth:`snapshot_now` serve the newest FIRST_ROWS of them and the trees
        around them (:mod:`~vmn_exp.core.index_lean_first`)."""
        if self._lean or self._snapshot is not None:
            return
        self._first_rows = self._newest_rows()
        if self._first_rows is not None:
            self._servable.set()

    def _newest_rows(self):
        if self._io is not None:  # the helper owns the files
            return first_rows_of(self.app_name, self._io.first_rows(FIRST_ROWS, FIRST_ROWS_MAX))
        return first_rows(self._store, self.app_name, FIRST_ROWS, FIRST_ROWS_MAX)

    def _set_published(self):
        self._published.set()
        self._servable.set()

    def _drop_folds(self):
        """Once a cold load is over and saved, hold its records as a warm
        restart does: each its run state alone, read back from the store
        when a refresh touches it. A free-threaded collection walks every
        live object, and the folds doubled them (plan 28 appendix A row 6)."""
        if not self.drops_folds:
            return  # a rebuild: its store closes once committed
        if self._unsaved.pending or self._rests or self._sweep.relisted_new() is not False:
            return  # still loading, or not all saved: the store lacks some
        lazy_of = getattr(self._store, "lazy_records", None)
        lazy = lazy_of(self.app_name, self._records) if lazy_of else None
        if lazy is not None:
            self._records.update(lazy)  # in place: an adopter shares the dict
            self._cold = False

    def _more_relisted(self, started):
        """Whether to load more of what a listing behind serving hands over
        in this refresh: during a bulk load (a cold index's) the next batch
        is waited for, up to BEHIND_REFRESH_SEC into the refresh — unless a
        journal hint waits for the next refresh."""
        while True:
            left = BEHIND_REFRESH_SEC - (self._monotonic() - started)
            if left <= 0 or self._sweep.hints_waiting():
                return False
            if self._sweep.relisted_ready():
                return True
            if not self._bulk_listing():
                return False
            self._sweep.wait_relisted(min(left, 1.0))

    def _bulk_listing(self):
        """Whether a listing behind serving brings many new records (a cold
        index's), not all handed over yet."""
        new = self._sweep.relisted_new()
        return new is None or bool(new and new[1] > _REMOTE_CHUNK and new[2])

    def _load_listed(self, listing, removed, started):
        # Unfinished claims and deleted records' leftovers have no metadata.
        refold = self._vmx.refold
        work = [
            (key, names, self._listed_record(key))
            for key, names in listing.items()
            if METADATA_FILE in names
        ]
        self._load_work(work, removed, started)
        self._vmx.refolded({k for k in refold.intersection(listing) if k not in self._unreadable})

    def _listed_record(self, key):
        """The record a listing of *key* refreshes: None (read afresh, whole)
        for one an upgrade's check found wrong (index_vmx_check)."""
        return None if key in self._vmx.refold else self._records.get(key)

    def _load_work(self, work, removed, started):
        unread = sum(record is None for _, _, record in work)
        self._freshness.loading(unread)
        if self._io is not None:  # the helper process persists them
            results = self._io.refresh(work, removed)
            self._io_unreadable = self._io.unreadable()
            self._apply(results, removed, started)
            self._save_mark(self._mark_puts(results, removed))
            return
        queue = self._load_queue(work)
        self._unread = unread
        try:
            chunk = self._take(queue)
            while queue:
                new = sum(record is None for _, _, record in chunk)
                self._unread -= new
                results = self._refresh_part(chunk, (), started, None)
                self._freshness.loaded(new)
                queue.want(self._unloaded_parents(results))
                chunk = self._take(queue)
        finally:
            self._unread = 0
        self._refresh_part(chunk, removed, started, started)

    def _derive_first(self, serve_kept=True):
        """Rows an upgrade left to re-derive are, from the persisted records
        (:mod:`~vmn_exp.core.index_derive`, no storage read), before they
        load; meanwhile the rows the upgrade kept (stale) or else an empty
        snapshot serve, ``loading`` the share done (republished at most every
        MIGRATING_PUBLISH_SEC; with an I/O helper, which owns the files and
        sends no progress, once). *serve_kept* False: none (an I/O helper's
        index, whose snapshots nobody reads). Whether any were."""
        io = self._io
        if io is None:
            deriving = getattr(self._store, "deriving", None)
            if deriving is None or not deriving(self.app_name):
                return False
        elif (total := io.deriving()) is None:
            return False
        if serve_kept and not self._lean:
            if self._first_rows is None:  # none of the newest: their total, at once
                self._first_rows = loading_snapshot(self.app_name, total if io is not None
                                                    else self._store.count(self.app_name))
                self._servable.set()
            with gc_paused():
                self._kept = kept_snapshot(self.app_name, io.kept() if io is not None
                                           else kept_parts(self._store, self.app_name))
        try:
            if io is None:
                self._store.derive(self.app_name, self._derived)
            else:  # the helper owns the files; no progress crosses
                self._derived(0, total)
                io.derive()
        finally:
            self._kept = None
        return True

    def _derived(self, done, total):
        self._freshness.migrating(done, total)
        if self._lean or (self._snapshot is not None
                          and self._monotonic() - self.published_at < MIGRATING_PUBLISH_SEC):
            return
        self.generation += 1
        if self._kept is not None:  # the kept rows, stale until re-derived
            self._snapshot = replace(self._kept, generation=self.generation,
                                     loading=(done, total))
        else:
            self._snapshot = self._rows.snapshot(
                self.app_name, self.generation, [], {}, loading=(done, total))
        self.published_at = self._monotonic()
        self._set_published()

    def _listing_phase(self, now):
        sweep = self._sweep
        if sweep._full_due(now) and not (sweep.journaled and sweep.behind):  # see freshness()
            return index_freshness.FULL_LISTING
        return index_freshness.JOURNAL if self._sweep.journaled else index_freshness.LISTING

    def _listing_position(self):
        """``position()`` -> the key a full listing's walk is at, when the
        storage tells (:meth:`~vmn_exp.storage.s3_listing.S3Listing.listing_position`)."""
        position_of = getattr(self._storage, "listing_position", None)
        return (lambda: position_of(self.app_name)) if position_of else None

    def _take(self, queue):
        """The queue's next chunk, a remote record not read yet cut to its
        row's files (:func:`first_objects`), its rest queued for later — during
        a bulk load behind serving, until its listing is over (then hinted)."""
        chunk = [(key, names, self._listed_record(key)) for key, names, _ in queue.take()]
        if not self._remote():
            return chunk
        cut, rest = [], []
        for key, names, record in chunk:
            if key in self._vmx.refold:  # whole, never rows-first: its row serves meanwhile
                cut.append((key, names, record))
                continue
            if record is None and queue.put_off(key):
                continue  # its row's part was set aside unread: read when due
            first = first_objects(names) if record is None else None
            cut.append((key, names if first is None else first, record))
            if first is not None:
                rest.append((key, names, None))
        if rest and self._bulk_listing():
            self._rests.update(key for key, _, _ in rest)
        else:
            queue.later(rest)
        return cut

    def _load_queue(self, work):
        """*work* queued so a remote cold load serves and keeps its records a
        chunk at a time, the newest first (their ancestors next), rather than
        only once every record was read."""
        if not work or not self._remote():
            return LoadQueue(work, len(work))
        return LoadQueue(sorted(work, key=_listed_at, reverse=True), _REMOTE_CHUNK)

    def _unloaded_parents(self, results):
        parents = ((record.get("meta") or {}).get("parent")
                   for _, record, _, _, _ in results if record is not None)
        return [p for p in parents if p and self._records.get(p) is None]

    def _refresh_part(self, work, removed, started, baseline_at):
        """Read, apply and persist *work*, with the listing baseline as of
        *baseline_at* (None: not the refresh's last part)."""
        results = self._refresh_local(work)
        with gc_paused():
            try:
                self._apply(results, removed, started)
            except BaseException:
                self._persist(results, removed)  # no baseline: the sweep missed some
                raise
            self._persist(results, removed, baseline_at)
        if self._snapshot is not None:
            self._set_published()
        return results

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


# ---------------------------------------------------------------------------
# Process-wide access with a direct fallback
# ---------------------------------------------------------------------------

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
