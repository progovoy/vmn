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
:meth:`refresh` still answer only once storage was listed.

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

Storage is duck-typed (``list_files``, ``load_file``, and optionally
``list_record_names``/``list_files(keys=)``/``direct_files``/``read_file_from``/
``plain_record_dir``/``index_cache_path``/``cache_identity``); like the rest of
``core`` this imports nothing from ``cli``, ``ui`` or ``exp``.
"""
import bisect
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext

from vmn_exp.core.fold import fold_log, fold_row
from vmn_exp.core.gc_pause import gc_paused
from vmn_exp.core import index_freshness
from vmn_exp.core.index_follower import apply_delta
from vmn_exp.core.index_baseline import ListingBaseline
from vmn_exp.core.index_bulk import BulkPublish, loading_snapshot
from vmn_exp.core.index_io_process import IOProcessError, start_io_process  # noqa: F401
from vmn_exp.core.index_journal_mark import JournalMark
from vmn_exp.core.index_lean_store import sort_timestamp as _timestamp
from vmn_exp.core.index_load_queue import LoadQueue
from vmn_exp.core.index_rows_first import first_objects
from vmn_exp.core.index_listing import ListingWatch
from vmn_exp.core.index_pending import PendingSave
from vmn_exp.core.index_point import index_path, shared_store
from vmn_exp.core.index_record import refresh_record, update_record
from vmn_exp.core.index_unreadable import Unreadable
from vmn_exp.core.index_remote_workers import RemoteLoaders, worker_count
from vmn_exp.core.index_rows import adopted as _adopted
from vmn_exp.core.index_rows import row_copies as _row_copies
from vmn_exp.core.index_snapshot import (
    IndexSnapshot,
    RowCache,
    new_side_tables,
    put_side_tables,
)
from vmn_exp.core.index_store import IndexStore
from vmn_exp.core.index_sweep import (
    DEFAULT_FULL_SWEEP_SEC,
    METADATA_FILE,
    Sweep,
)
from vmn_exp.core.index_views import lean_row
from vmn_exp.core.index_workers import load_new_records
from vmn_exp.core.log import load_log
from vmn_exp.core.status import load_run_state, observed_at_by_verstr
from vmn_exp.core.traced_lock import TracedLock

_LOGGER = logging.getLogger(__name__)
# Records a remote backend re-reads at once (each costs a few round trips).
_REMOTE_WORKERS = 32
# Records a remote backend reads between persisting what it has (and, while
# the index is small, publishing it: see index_bulk).
_REMOTE_CHUNK = 500
# How long a refresh of a cold remote index keeps loading what its listing
# behind serving hands over before letting the next refresh serve the
# journal's hints (and the ui see the refresh end, not a stuck one).
BEHIND_REFRESH_SEC = 30.0
# How long a request on an index that published nothing yet waits for its
# first snapshot before it gets an empty one saying it is loading.
FIRST_SNAPSHOT_WAIT_SEC = 0.5
_BISECT_NEW = 64  # new records past which the order is merged, not inserted into
# Seconds between the empty snapshots a re-derive publishes its progress in.
MIGRATING_PUBLISH_SEC = 1.0
# A record a refresh could not read is read again this long after (doubling).
RETRY_UNREADABLE_SEC = 60.0
_monotonic = time.monotonic


def _listed_at(work_item):
    """When the listing saw *work_item*'s metadata.yml written (a remote
    backend's ``(size, mtime, etag)`` signature), 0 when it does not say."""
    sig = work_item[1].get(METADATA_FILE)
    return sig[1] if isinstance(sig, (list, tuple)) and len(sig) > 1 else 0


class ExperimentIndex:
    """Incrementally maintained rows for one app of one storage backend."""

    def __init__(
        self, storage, app_name, cache_path=None, full_sweep_sec=DEFAULT_FULL_SWEEP_SEC,
        cache_store=None,
    ):
        self._storage = storage
        self.app_name = app_name
        self._cache_path = cache_path
        self._store = cache_store or IndexStore(cache_path)
        self._unsaved = PendingSave()  # what a failed save left to persist
        self._freshness = index_freshness.Freshness(lambda: self._io or self._store, app_name)
        self._sweep = Sweep(storage, app_name, full_sweep_sec)
        self._baseline = ListingBaseline(self._store, app_name)
        self._mark = JournalMark(self._store, app_name)
        self._io = None  # the I/O helper process, once use_io_process() started it
        self._records = None
        self._order = None  # record keys in storage order
        self._stamps = None  # their timestamps, for bisecting new keys in
        self._reorder = ((), False)  # (new keys, whether one was re-described)
        self._rows = RowCache()
        self._bulk = BulkPublish()
        self._snapshot = None
        self._placeholder = None  # (expected, the empty snapshot saying so)
        self._loaders = None  # a bulk load's worker processes (index_remote_workers)
        self._rests = set()  # records a bulk load read rows-first, the rest to read
        self._unreadable = Unreadable(app_name, lambda: _monotonic())
        self._io_unreadable = None  # the I/O helper's Unreadable.summary(), after its refresh
        self._lock = TracedLock(f"index refresh:{app_name}")
        self._published = threading.Event()  # a first snapshot, or a refresh that failed
        self._revalidator = None  # the thread a warm snapshot() started
        self._revalidator_lock = threading.Lock()
        self.generation = 0
        self.last_refresh_at = None  # monotonic start of the last refresh
        self.published_at = None  # monotonic time the current snapshot was built
        self._cache_gen = None  # a follower's CacheStore generation; None for a leader
        self._lean = False  # see sync()
        self._lean_index = None  # the lean copy sync() refreshes while this one is unloaded
        self._unread = 0  # new records a chunked refresh has yet to read

    @classmethod
    def follower(cls, cache_store, scope):
        """An index that never reads storage: each refresh applies
        *cache_store*'s ``load_since`` deltas, which a leader saves."""
        index = cls(None, scope)
        index._store = cache_store
        index._cache_gen = 0
        return index

    @property
    def path(self):
        """The file the index persists in, or None."""
        return getattr(self._store, "path", None)

    @property
    def full_sweep_sec(self):
        """Seconds between full listings (default 300); 0 lists fully every time."""
        return self._sweep.full_sweep_sec

    @full_sweep_sec.setter
    def full_sweep_sec(self, value):
        self._sweep.full_sweep_sec = value

    @property
    def journaled(self):
        """True: refreshes list only hinted and live records (plan 11 §5.2)."""
        return self._sweep.journaled

    @journaled.setter
    def journaled(self, value):
        self._sweep.journaled = value

    def hint(self, name):
        """The store's journal named *name*: the next refresh re-reads it (and
        loads it, if new) without listing anything else."""
        self._sweep.hint(name)

    def journal_at(self, ms):
        """The journal hinted every entry up to *ms* (its reader's cursor):
        once refreshed, the records stand at that mark (persisted with them)."""
        self._sweep.journal_at(ms)

    def resume_journal(self, oldest_ms):
        """Carry on from the persisted records when their journal mark is
        no older than *oldest_ms* (the oldest entry the journal still holds):
        no full listing, the caller replays the journal from the mark it
        returns. None: no such mark — the index needs :meth:`reconcile`."""
        mark = self._mark.load()
        if mark is None or mark < oldest_ms:
            return None
        self._sweep.resume()
        return mark

    def overflowed(self, names):
        """The journal named too many of the app's records in one tick:
        re-read *names* and list the record names (not their files) for
        anything else it missed."""
        self._sweep.overflowed(names)

    @property
    def drift(self):
        """Records the consistency check found changed with no journal entry."""
        return self._sweep.drift

    @property
    def last_reconcile_at(self):
        """Wall time the last full listing or consistency round began."""
        return self._sweep.last_reconcile_at

    @property
    def records(self):
        """A copy of ``{key: record}`` as last refreshed."""
        return dict(self._records or {})

    @property
    def record_count(self):
        return len(self._records or ())

    @property
    def published(self):
        """The current snapshot, or None before the first (never waits)."""
        return self._snapshot

    @property
    def refreshing(self):
        """True while a refresh holds the index (diagnostics; never waits)."""
        return self._lock.locked()

    def freshness(self):
        """``{as_of, refreshing, phase, progress}`` of the current snapshot
        (:mod:`~vmn_exp.core.index_freshness`), plus ``stalled_sec`` while a
        refresh runs; never waits. A journaled index's full listing behind
        serving (progress: the share of records listed) or catch-up on the
        journal (a replay, an overflow, hints queued) shows as
        ``full_listing``/``journal`` between refreshes too. ``unreadable``
        (:meth:`Unreadable.summary`: the I/O helper's, which reads the
        records) counts the records set aside, absent when none."""
        state = self._reported_freshness()
        if state["refreshing"]:
            state["stalled_sec"] = self._freshness.stalled_sec(state["phase"], state["progress"])
        unreadable = self._io_unreadable if self._io is not None else self._unreadable.summary()
        if unreadable:
            state["unreadable"] = unreadable
        return state

    def _reported_freshness(self):
        state = self._freshness.state(self._lock.locked())
        behind = self._sweep.listing_phase()
        if state["phase"] == index_freshness.MIGRATING:
            return state
        if behind is not None and (
                behind[0] == index_freshness.FULL_LISTING or state["phase"] == index_freshness.IDLE):
            state["phase"], state["progress"] = behind
        new = self._sweep.relisted_new()
        loading = self._loading(len(self._order or ()))
        if loading is not None and (new is None or (new and new[1] > _REMOTE_CHUNK)):
            rows, expected = loading  # a cold index's load behind serving: the share served
            state["progress"] = round(rows / expected, 3) if expected else None
        return state

    def full_listing_due(self):
        """Whether the next refresh lists storage fully (diagnostics)."""
        return self._sweep._full_due(_monotonic())

    def reconcile(self):
        """Make the next refresh a full listing."""
        self._sweep.request_full()

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
                               self.full_sweep_sec, self._store)
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
        if fresh_at is not None and _monotonic() - fresh_at < max_age_sec:
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
            if self._store is not other._store:
                self._baseline = ListingBaseline(self._store, self.app_name)
                self._mark = JournalMark(self._store, self.app_name)
            else:
                self._baseline, self._mark = other._baseline, other._mark
            self.generation += 1
            self._snapshot = self._build_snapshot()

    def _refresh_locked(self):
        started = _monotonic()
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
        except Exception:
            # A listing's changes may have been taken but not applied: list
            # them again — all of them once a dead I/O helper took its
            # baselines along.
            if self._io is not None and not self._io.alive():
                self._sweep.reset()
            else:
                self._sweep.failed()
            raise
        finally:
            self._published.set()
            self._freshness.idle()
        self.last_refresh_at = started
        self._freshness.refreshed()

    def _paused_unless_remote(self):
        """A local refresh is bulk work throughout, so collection pauses for
        all of it (see :mod:`~vmn_exp.core.gc_pause`). A remote one pauses it
        only to decode and fold, never across its listing and reads: at 486k
        records on S3 those take hours, and the process's garbage piled up."""
        return nullcontext() if self._remote() else gc_paused()

    def _refresh_from_storage(self, started):
        if self._records is None:
            placeholder = self._derive_first()
            if self._keeps_baseline():  # read before the records it vouches for
                self._baseline.load(self._sweep, started)
            with gc_paused():
                self._records = self._load_records()
                if not self._lean and (placeholder or (
                        self._records and self._snapshot is None)):
                    self._publish_persisted()
        self._sweep.behind = self._io is None and self._remote()
        self._freshness.listing(self._listing_phase(started), self._records,
                                self._listing_position())
        listing, removed = self._sweep.listing(self._records, started)
        self._unreadable.forget(self._sweep.listed_gone)
        self._load_listed(listing, removed, started)
        while self._more_relisted(started):
            self._load_listed(*self._sweep.next_relisted(self._records, _monotonic()), started)
        if self._snapshot is None and not self._lean:  # a refresh ends with one
            self._publish_pending()
        if self._rests and self._sweep.relisted_new() is False:
            for key in self._rests:  # what rows-first left unread: listed afresh
                self._sweep.hint(key)
            self._rests = set()

    def _more_relisted(self, started):
        """Whether to load more of what a listing behind serving hands over
        in this refresh: during a bulk load (a cold index's) the next batch
        is waited for, up to BEHIND_REFRESH_SEC into the refresh — unless a
        journal hint waits for the next refresh."""
        while True:
            left = BEHIND_REFRESH_SEC - (_monotonic() - started)
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
        work = [
            (key, names, self._records.get(key))
            for key, names in listing.items()
            if METADATA_FILE in names
        ]
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

    def _derive_first(self):
        """Rows an upgrade left to re-derive are, from the persisted records
        (:mod:`~vmn_exp.core.index_derive`, no storage read), before they
        load; meanwhile an empty snapshot ``loading`` the share done serves
        (republished at most every MIGRATING_PUBLISH_SEC). Whether any were."""
        if self._io is not None:  # the helper owns the files; no progress crosses
            total = self._io.deriving()
            if total is None:
                return False
            self._derived(0, total)
            self._io.derive()
            return True
        deriving = getattr(self._store, "deriving", None)
        if deriving is None or not deriving(self.app_name):
            return False
        self._store.derive(self.app_name, self._derived)
        return True

    def _derived(self, done, total):
        self._freshness.migrating(done, total)
        if self._lean or (self._snapshot is not None
                          and _monotonic() - self.published_at < MIGRATING_PUBLISH_SEC):
            return
        self.generation += 1
        self._snapshot = self._rows.snapshot(
            self.app_name, self.generation, [], {}, loading=(done, total))
        self.published_at = _monotonic()
        self._published.set()

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
        chunk = [(key, names, self._records.get(key)) for key, names, _ in queue.take()]
        if not self._remote():
            return chunk
        cut, rest = [], []
        for key, names, record in chunk:
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
            self._published.set()
        return results

    def _apply(self, results, removed, started):
        touched, new, redescribed = set(), [], False
        for key, record, dirty, moved, state_moved in results:
            old = self._records.get(key)
            if old is not None and (dirty or state_moved):
                self._sweep.touch(key, started)
            if record is None:
                continue  # the helper found nothing to change
            if old is None:
                new.append(key)
            elif moved:
                redescribed = True
            if old is None or dirty or state_moved:
                touched.add(key)
                self._sweep.track(key, record)
            if dirty:
                self._rows.pop(key, None)
            self._records[key] = _adopted(old, record, state_moved)
        for key in removed:
            del self._records[key]
            self._rows.pop(key, None)
            self._sweep.forget(key)
        self._unreadable.forget(removed)
        if not self._lean:
            self._publish(new, removed, redescribed, touched)

    def _publish(self, new, removed, redescribed, touched):
        """Publish what changed — while a bulk load has many records to go,
        only once due (:mod:`~vmn_exp.core.index_bulk`)."""
        bulk, backlog = self._bulk, self._backlog()
        self._number_later(backlog)
        if not backlog and self._sweep.relisted_new() is False:  # the bulk load is over
            self._close_loaders()
        bulk.add(new, removed, redescribed, touched)
        snap = self._snapshot
        if snap is None and not bulk.pending() and self._bulk_listing():
            return  # nothing loaded yet: requests get loading_snapshot meanwhile
        if snap is not None and backlog and not bulk.due(len(snap.rows), _REMOTE_CHUNK):
            return
        self._publish_pending()

    def _publish_pending(self):
        bulk, snap, started = self._bulk, self._snapshot, _monotonic()
        new, resort, touched = bulk.take()
        # Only a new, removed or re-described record can move in the order.
        if new or resort or self._order is None:
            self._reorder = (new, resort)
            self._order = self._sorted_keys()
        if touched is None or touched or snap is None:
            self.generation += 1
            self._snapshot = self._build_snapshot(touched)
            bulk.published(started)

    def _backlog(self):
        """Whether a load has many records yet to read: more than a chunk of
        this refresh's past the current one, or of the new names a listing
        behind serving found and has not handed over."""
        new = self._sweep.relisted_new()
        return max(self._unread, new[2] if new else 0) > _REMOTE_CHUNK

    def _loading(self, rows):
        """``(rows loaded, rows expected)`` while a load reads many new
        records (expected None while a cold index's listing named none
        yet), else None."""
        new = self._sweep.relisted_new()
        if new is None:
            return (rows, None) if not self._records else None
        known, seen, left = new or (0, 0, 0)
        if self._unread or (seen > _REMOTE_CHUNK and left):
            return rows, max(known + seen, len(self._records) + self._unread)
        return None

    def _number_later(self, later):
        """While *later* (a bulk load prepending records, which would
        renumber every persisted row per chunk), let the store leave its
        rows' ``idx`` stale; once not, it numbers them (see
        :meth:`~vmn_exp.core.index_store.SqliteStore.number_later`)."""
        number_later = getattr(self._store, "number_later", None)
        if number_later is not None:
            number_later(self.app_name, later)

    def _keeps_baseline(self):
        """Whether listing baselines persist: not for a journaled sweep, one
        whose listings run in the I/O helper process, or one listing fully
        every time (nothing to carry on from)."""
        return self._io is None and not self._sweep.journaled and bool(self.full_sweep_sec)

    def _publish_persisted(self):
        """Serve the records as persisted until the listing under way
        revalidates them."""
        self._order = self._sorted_keys()
        self.generation += 1
        self._snapshot = self._build_snapshot()
        self._published.set()

    def _refresh_from_cache(self):
        if self._records is None:
            self._records = {}
        old = set(self._records)
        changed, removed, self._cache_gen = apply_delta(
            self._records, self._store, self.app_name, self._cache_gen
        )
        for key in changed | removed:
            self._rows.pop(key, None)
        new = [key for key in changed if key not in old]
        # A changed record may have been re-described (its timestamp moved).
        self._reorder = (new, bool(removed) or len(new) < len(changed))
        self._order = self._sorted_keys()
        if changed or removed or self._snapshot is None:
            self.generation += 1
            self._snapshot = self._build_snapshot(None if removed else changed)

    def _load_records(self):
        if self._io:
            return self._io.load()
        lazy_of = getattr(self._store, "load_lazy", None) if self._lean else None
        lazy = lazy_of(self.app_name) if lazy_of else None
        if lazy is not None:
            return lazy
        warm = getattr(self._store, "load_warm", None)
        loaded = warm(self.app_name) if warm else None
        if loaded is None:
            return self._store.load(self.app_name)
        records, self._order, lean, self._stamps = loaded
        self._rows.seed(lean)
        return records

    def _refresh_and_persist(self, work, removed):
        """``(key, record, dirty, moved, state moved)`` per item of *work*,
        persisted with *removed*: what the helper process's index answers
        (``None`` records stand for those it found unchanged)."""
        results = self._refresh_local(work)
        self._persist(results, removed)
        self._unreadable.forget(removed)
        return results

    def _refresh_local(self, work):
        direct_files = getattr(self._storage, "direct_files", None)
        return self._refresh_records(work, direct_files() if direct_files else self._storage)

    def _persist(self, results, removed, started=None):
        """Save *results* with *removed*, then — given the refresh's
        *started* — the listing baseline: in the same transaction when the
        store joins them, else only once nothing is left unsaved."""
        baseline = started is not None and self._keeps_baseline()
        joins = getattr(self._store, "JOINS_KV", False)
        joint = baseline and joins
        puts = self._baseline.puts(self._sweep, started) if joint else None
        marks = self._mark_puts(results, removed) if started is not None else []
        saved = self._unsaved.save(
            self._store, self.app_name,
            {key: record for key, record, dirty, _, _ in results if dirty},
            removed,
            {key: record for key, record, _, _, state_moved in results if state_moved},
            (puts or []) + marks if joins else puts,
        )
        if puts and not saved:
            self._baseline.forget()
        elif baseline and not joint and saved:
            self._baseline.save(self._sweep, started)
        if saved:
            self._mark.saved(marks) if joins else self._save_mark(marks)

    def _mark_puts(self, results, removed):
        changed = bool(removed) or any(dirty or state_moved for _, _, dirty, _, state_moved in results)
        return self._mark.puts(self._sweep.persistable_mark(), changed)

    def _save_mark(self, puts):
        for put in puts:
            self._store.kv_put(*put)
        self._mark.saved(puts)

    def _refresh_records(self, work, direct):
        """``(key, record, dirty, moved, state moved)`` per ``(key, names,
        record)`` in *work*.

        A cold build's many new local records load in worker processes; a
        remote backend's records are re-read concurrently: each costs a few
        round trips, and a cold index on S3 would otherwise pay them serially.
        """
        done = load_new_records(self._storage, direct, self.app_name, work)
        if not done and self._backlog():
            done = self._remote_loaders().load(self.app_name, work, self._unreadable)
        todo = [w for w in work if w[0] not in done]
        done.update(zip((w[0] for w in todo), self._refresh_all(todo, direct)))
        return [(key, *done[key]) for key, _, _ in work]

    def _remote_loaders(self):
        """The worker processes a bulk load of a remote backend reads its new
        records in (:mod:`~vmn_exp.core.index_remote_workers`): started once,
        none when the backend cannot be opened again elsewhere."""
        if self._loaders is None:
            spec_of = getattr(self._storage, "worker_spec", None)
            spec = spec_of() if spec_of and self._remote() else None
            self._loaders = RemoteLoaders(spec, worker_count() if spec else 0)
        return self._loaders

    def _close_loaders(self):
        loaders, self._loaders = self._loaders, None
        if loaders is not None:
            loaders.close()

    def _refresh_all(self, work, direct):
        if len(work) > 1 and self._remote():
            # A warm start's lazy records read their stored head here, in
            # order (a chunk per query), never from the pool's threads.
            for _, _, record in work:
                if record is not None:
                    record.get("meta_sig")
            with ThreadPoolExecutor(max_workers=_REMOTE_WORKERS,
                                    thread_name_prefix="vmn-index-load") as pool:
                return list(pool.map(lambda w: self._refresh_one(*w, direct), work))
        return [self._refresh_one(*w, direct) for w in work]

    def _remote(self):
        is_remote = getattr(self._storage, "is_remote", None)
        return bool(is_remote and is_remote())

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

    # -- snapshots -----------------------------------------------------------

    def _build_snapshot(self, touched=None):
        order = self._order or []
        self.published_at = _monotonic()
        return self._rows.snapshot(
            self.app_name, self.generation, order, self._records, touched,
            self._loading(len(order)),
        )

    def snapshot_now(self, wait_sec=FIRST_SNAPSHOT_WAIT_SEC):
        """The current :class:`IndexSnapshot`, never waiting for a first load
        longer than *wait_sec* (what a background-refreshed server serves):
        until one is published, an empty snapshot whose ``loading`` is ``(0,
        records expected)`` — None while not even their names are listed."""
        snap = self._snapshot
        if snap is not None or self._cache_gen is not None:
            return snap or self._first_load()
        self._revalidate_in_background()
        self._published.wait(wait_sec)
        snap = self._snapshot
        if snap is not None:
            return snap
        new = self._sweep.relisted_new()
        expected = new[0] + new[1] if new else None
        if self._placeholder is None or self._placeholder[0] != expected:
            self._placeholder = (expected, loading_snapshot(self.app_name, expected))
        return self._placeholder[1]

    def snapshot(self):
        """The current :class:`IndexSnapshot`. The first call of an index
        with persisted records answers them as soon as they are read and
        refreshes them from storage in the background; a cold index answers
        once its first load is done."""
        snap = self._snapshot
        if snap is not None:
            return snap
        if self._cache_gen is not None:
            return self._first_load()
        self._revalidate_in_background()
        self._published.wait()
        # The background load failed: load here, meeting its error.
        return self._snapshot or self._first_load()

    def _revalidate_in_background(self):
        with self._revalidator_lock:
            if self._revalidator is not None:
                return
            self._revalidator = threading.Thread(
                target=self._revalidate, daemon=True, name="vmn-index-revalidate"
            )
            self._revalidator.start()

    def _revalidate(self):
        try:
            self.refresh()
        except Exception:
            _LOGGER.debug("Background index refresh failed", exc_info=True)

    def wait_revalidated(self, timeout=None):
        """Wait for the refresh a first :meth:`snapshot` started, if any."""
        if self._revalidator is not None:
            self._revalidator.join(timeout)

    # -- copies of the current snapshot (call refresh() first) ---------------

    def rows(self, with_create_note=False):
        """``experiment_row`` dicts in storage order — fresh copies, ``idx`` and
        ``metric_summary`` and ``outputs`` set.

        ``with_create_note`` adds ``create_note``: the first ``create`` entry's
        note, which ``vmn-exp list`` shows for a run without a metadata note.
        """
        snap = self._snapshot
        return _row_copies(snap, with_create_note) if snap is not None else []

    def run_states(self):
        """``{verstr: raw run state or None}`` for the rows' experiments."""
        snap = self._snapshot
        return dict(snap.run_states) if snap is not None else {}


# ---------------------------------------------------------------------------
# Process-wide access with a direct fallback
# ---------------------------------------------------------------------------

_SHARED = {}
_SHARED_LOCK = threading.Lock()


def shared_index(storage, app_name, cache_path=None, full_sweep_sec=None):
    """The process-wide index for *storage*'s *app_name* data.

    Keyed by the backend's ``cache_identity()`` so equivalent storage objects
    share one warm index. Persisted at *cache_path* when given (the ui keeps its
    own under the server data dir), else at the backend's ``index_cache_path``.
    A *full_sweep_sec* other than None sets that index's sweep interval.
    """
    index = _process_index(storage, app_name, cache_path)
    if full_sweep_sec is not None:
        index.full_sweep_sec = full_sweep_sec
    return index


def _process_index(storage, app_name, cache_path):
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
        return ExperimentIndex(storage, app_name, cache_path, cache_store=store)
    key = (identity, app_name, cache_path)
    with _SHARED_LOCK:
        index = _SHARED.get(key)
        if index is None:
            index = _SHARED[key] = ExperimentIndex(storage, app_name, cache_path,
                                                   cache_store=store)
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


def _direct_folds(storage, app_name, read_log):
    metas = storage.list_snapshots(app_name)
    for idx, meta in enumerate(metas, 1):
        yield idx, meta, fold_log(read_log(storage, app_name, meta["verstr"]))


def _run_states(storage, app_name, rows, read_run_state=load_run_state):
    return {r["verstr"]: read_run_state(storage, app_name, r["verstr"]) for r in rows}


def snapshot_of_folds(app_name, folds, run_states=None):
    """An :class:`IndexSnapshot` (generation 0) of *folds*, ``(idx, metadata,
    fold)`` per run; ``run_states(rows)`` gives the runs' ``(run states,
    observed_at)`` once their rows are built (none without it)."""
    rows, notes, sides = [], {}, new_side_tables()
    for idx, meta, fold in folds:
        verstr = meta["verstr"]
        row, notes[verstr], *values = lean_row(idx, meta, fold)
        rows.append(row)
        put_side_tables(sides, verstr, values)
    states, observed = run_states(rows) if run_states else ({}, {})
    return IndexSnapshot.build(app_name, 0, rows, states, notes, observed, **sides)


def direct_snapshot(storage, app_name, schema=None, read_log=load_log,
                    read_run_state=load_run_state):
    """An :class:`IndexSnapshot` (generation 0) built by reading every record
    (with the caller's loaders), summarized by *schema* like
    :func:`indexed_snapshot`'s."""

    def run_states(rows):
        states = _run_states(storage, app_name, rows, read_run_state)
        return states, observed_at_by_verstr(storage, app_name, states)

    folds = _direct_folds(storage, app_name, read_log)
    return snapshot_of_folds(app_name, folds, run_states).summarized(schema)


def indexed_snapshot(
    storage,
    app_name,
    cache_path=None,
    max_age_sec=0,
    full_sweep_sec=None,
    wait=False,
    fallback=direct_snapshot,
    schema=None,
):
    """The shared index's :class:`IndexSnapshot`, refreshed when older than a
    positive *max_age_sec* (the default 0 takes a loaded index as it is: see
    :meth:`ExperimentIndex.refresh_if_stale`) — or, with *wait*, refreshed now
    even if another thread's refresh has to finish first. *full_sweep_sec* is passed on to
    :func:`shared_index`. Rows follow the metrics *schema* the caller passes
    (:meth:`IndexSnapshot.summarized`), none by default. If the index fails,
    ``fallback(storage, app_name, schema)`` answers instead; a None
    *fallback* returns None."""
    try:
        index = shared_index(storage, app_name, cache_path, full_sweep_sec)
        snap = index.refresh().snapshot() if wait else index.refresh_if_stale(max_age_sec)
        return snap.summarized(schema)
    except Exception:
        _LOGGER.debug("Experiment index unavailable", exc_info=True)
        return fallback(storage, app_name, schema) if fallback else None


def indexed_status_rows(
    storage, app_name, with_create_note=False, cache_path=None, schema=None
):
    """``(rows, run_states, observed_at)`` from an up-to-date snapshot — fresh
    row copies (see :meth:`ExperimentIndex.rows`), the run states and
    ``{verstr: run_state.yml store write time}``, the ``observed_at`` a status
    derivation takes. *schema*: see :func:`indexed_snapshot`."""
    snap = indexed_snapshot(storage, app_name, cache_path, wait=True, schema=schema)
    return (
        _row_copies(snap, with_create_note),
        dict(snap.run_states),
        dict(snap.run_state_observed_at),
    )
