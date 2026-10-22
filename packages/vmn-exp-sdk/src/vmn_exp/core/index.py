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

from vmn_exp.core.fold import fold_log, fold_row
from vmn_exp.core.gc_pause import gc_paused
from vmn_exp.core.index_follower import apply_delta
from vmn_exp.core.index_baseline import ListingBaseline
from vmn_exp.core.index_io_process import IOProcessError, start_io_process  # noqa: F401
from vmn_exp.core.index_lean_store import sort_timestamp as _timestamp
from vmn_exp.core.index_listing import ListingWatch
from vmn_exp.core.index_pending import PendingSave
from vmn_exp.core.index_point import index_path, shared_store
from vmn_exp.core.index_record import refresh_record, update_record
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

_LOGGER = logging.getLogger(__name__)
# Records a remote backend re-reads at once (each costs a few round trips).
_REMOTE_WORKERS = 32
# Records a remote backend reads between publishing and persisting what it has.
_REMOTE_CHUNK = 500
_monotonic = time.monotonic


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
        self._sweep = Sweep(storage, app_name, full_sweep_sec)
        self._baseline = ListingBaseline(self._store, app_name)
        self._io = None  # the I/O helper process, once use_io_process() started it
        self._records = None
        self._order = None  # record keys in storage order
        self._stamps = None  # their timestamps, for bisecting new keys in
        self._reorder = ((), False)  # (new keys, whether one was re-described)
        self._rows = RowCache()
        self._snapshot = None
        self._lock = threading.Lock()
        self._published = threading.Event()  # a first snapshot, or a refresh that failed
        self._revalidator = None  # the thread a warm snapshot() started
        self._revalidator_lock = threading.Lock()
        self.generation = 0
        self.last_refresh_at = None  # monotonic start of the last refresh
        self._cache_gen = None  # a follower's CacheStore generation; None for a leader
        self._lean = False  # see sync()
        self._lean_index = None  # the lean copy sync() refreshes while this one is unloaded

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
        loaded in-process, or no helper could start. :meth:`close` stops it."""
        with self._lock:
            if self._io is None and self._records is None:
                self._io = start_io_process(self._storage, self.app_name, self._cache_path)
                if self._io is not None:
                    self._sweep.watch = self._io.watch
            return self._io is not None

    def close(self):
        """Stop the I/O helper process, if any; later refreshes run in-process
        from a full listing."""
        with self._lock:
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
            self._rows, self._sweep = other._rows, other._sweep
            self._store, self._unsaved = store or other._store, other._unsaved
            if self._store is not other._store:
                self._baseline = ListingBaseline(self._store, self.app_name)
            else:
                self._baseline = other._baseline
            self.generation += 1
            self._snapshot = self._build_snapshot()

    def _refresh_locked(self):
        started = _monotonic()
        if self._cache_gen is not None:
            self._refresh_from_cache()
            self.last_refresh_at = started
            return
        try:
            with gc_paused():
                self._refresh_from_storage(started)
        except Exception:
            # A listing's changes may have been taken but not applied.
            self._sweep.reset()
            raise
        finally:
            self._published.set()
        self.last_refresh_at = started

    def _refresh_from_storage(self, started):
        if self._records is None:
            if self._keeps_baseline():  # read before the records it vouches for
                self._baseline.load(self._sweep, started)
            self._records = self._load_records()
            if self._records and self._snapshot is None and not self._lean:
                self._publish_persisted()
        listing, removed = self._sweep.listing(self._records, started)

        # Unfinished claims and deleted records' leftovers have no metadata.
        work = [
            (key, names, self._records.get(key))
            for key, names in listing.items()
            if METADATA_FILE in names
        ]
        if self._io is not None:  # the helper process persists them
            self._apply(self._io.refresh(work, removed), removed, started)
            return
        *early, last = self._chunks(work)
        for chunk in early:
            self._refresh_part(chunk, (), started, None)
        self._refresh_part(last, removed, started, started)

    def _chunks(self, work):
        """*work* split so a remote cold load serves and keeps its records a
        chunk at a time, rather than only once every record was read."""
        if not work or not self._remote():
            return [work]
        return [work[i:i + _REMOTE_CHUNK] for i in range(0, len(work), _REMOTE_CHUNK)]

    def _refresh_part(self, work, removed, started, baseline_at):
        """Read, apply and persist *work*, with the listing baseline as of
        *baseline_at* (None: not the refresh's last part)."""
        results = self._refresh_local(work)
        try:
            self._apply(results, removed, started)
        except BaseException:
            self._persist(results, removed)  # no baseline: the sweep missed some
            raise
        self._persist(results, removed, baseline_at)
        if self._snapshot is not None:
            self._published.set()

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
        if not self._lean:
            self._publish(new, removed, redescribed, touched)

    def _publish(self, new, removed, redescribed, touched):
        # Only a new, removed or re-described record can move in the order.
        if new or removed or redescribed or self._order is None:
            self._reorder = (new, redescribed or bool(removed))
            self._order = self._sorted_keys()
        if touched or removed or self._snapshot is None:
            self.generation += 1
            self._snapshot = self._build_snapshot(None if removed else touched)

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
        return results

    def _refresh_local(self, work):
        direct_files = getattr(self._storage, "direct_files", None)
        return self._refresh_records(work, direct_files() if direct_files else self._storage)

    def _persist(self, results, removed, started=None):
        """Save *results* with *removed*, then — given the refresh's
        *started* — the listing baseline: in the same transaction when the
        store joins them, else only once nothing is left unsaved."""
        baseline = started is not None and self._keeps_baseline()
        joint = baseline and getattr(self._store, "JOINS_KV", False)
        puts = self._baseline.puts(self._sweep, started) if joint else None
        saved = self._unsaved.save(
            self._store, self.app_name,
            {key: record for key, record, dirty, _, _ in results if dirty},
            removed,
            {key: record for key, record, _, _, state_moved in results if state_moved},
            puts,
        )
        if puts and not saved:
            self._baseline.forget()
        elif baseline and not joint and saved:
            self._baseline.save(self._sweep, started)

    def _refresh_records(self, work, direct):
        """``(key, record, dirty, moved, state moved)`` per ``(key, names,
        record)`` in *work*.

        A cold build's many new local records load in worker processes; a
        remote backend's records are re-read concurrently: each costs a few
        round trips, and a cold index on S3 would otherwise pay them serially.
        """
        done = load_new_records(self._storage, direct, self.app_name, work)
        todo = [w for w in work if w[0] not in done]
        done.update(zip((w[0] for w in todo), self._refresh_all(todo, direct)))
        return [(key, *done[key]) for key, _, _ in work]

    def _refresh_all(self, work, direct):
        if len(work) > 1 and self._remote():
            # A warm start's lazy records read their stored head here, in
            # order (a chunk per query), never from the pool's threads.
            for _, _, record in work:
                if record is not None:
                    record.get("meta_sig")
            with ThreadPoolExecutor(max_workers=_REMOTE_WORKERS) as pool:
                return list(pool.map(lambda w: self._refresh_one(*w, direct), work))
        return [self._refresh_one(*w, direct) for w in work]

    def _remote(self):
        is_remote = getattr(self._storage, "is_remote", None)
        return bool(is_remote and is_remote())

    def _refresh_one(self, key, names, record, direct):
        return refresh_record(key, names, record, lambda *a: self._update(*a, direct))

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
        order = list(self._order)
        for key in new:
            meta = self._records[key]["meta"]
            if meta is None:
                continue  # not an experiment
            stamp = (_timestamp(meta), key)
            at = bisect.bisect_right(self._stamps, stamp)
            self._stamps.insert(at, stamp)
            order.insert(at, key)
        return order

    # -- snapshots -----------------------------------------------------------

    def _build_snapshot(self, touched=None):
        return self._rows.snapshot(
            self.app_name, self.generation, self._order or [], self._records, touched
        )

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
