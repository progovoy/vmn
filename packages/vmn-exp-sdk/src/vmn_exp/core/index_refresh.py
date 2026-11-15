#!/usr/bin/env python3
"""How :class:`~vmn_exp.core.index.ExperimentIndex` refreshes: the locked
refresh from storage (or a follower's cache), its first load, the I/O
helper process, adopting a rebuild and an upgrade's vmx check (a mixin; all
state stays on the index). The retry interval tests patch is read through
the ``_retry_sec()`` seam in core/index.py.

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
which of these it is busy with, between refreshes too."""
import logging
from contextlib import nullcontext

from vmn_exp.core.gc_pause import gc_paused
from vmn_exp.core.index_baseline import ListingBaseline
from vmn_exp.core.index_io_process import start_io_process
from vmn_exp.core.index_journal_mark import JournalMark
from vmn_exp.core.index_listing import ListingWatch
from vmn_exp.core.index_reread import hint_unloaded

_LOGGER = logging.getLogger("vmn_exp.core.index")


class IndexRefresh:
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
        for key in self._unreadable.due(self._retry_sec()):
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
