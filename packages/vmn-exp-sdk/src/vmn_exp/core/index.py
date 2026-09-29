#!/usr/bin/env python3
"""An incremental index of an app's experiments: leaderboard rows without
re-reading every log whenever anything changes.

Which records a refresh looks at is :mod:`experiment_index_sweep`'s call: by
default all of them; with ``full_sweep_sec`` set (opt-in, for a server that
refreshes often), the new and live ones from a names-only listing and all of
them every ``full_sweep_sec``. Of those only what moved is read: a new record
is loaded, a changed ``metadata.yml`` re-read, a grown log read from where it
was last read up to (:mod:`experiment_index_logs`), a rewritten
``run_state.yml`` — a heartbeat — re-read on its own. The folded state
persists in SQLite (:mod:`experiment_index_store`), so a new process starts
warm; a heartbeat there rewrites only its small run-state row.

Readers get an immutable :class:`IndexSnapshot` per ``generation`` (bumped by
anything visible, run states included) that never takes the index lock or
touches storage. Its rows are exactly ``experiment_row``'s; status is derived
from its run states on every read, since it depends on the clock.

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

from vmn_exp.core.index_io_process import IOProcessError, start_io_process  # noqa: F401
from vmn_exp.core.index_listing import ListingWatch
from vmn_exp.core.index_record import refresh_record, update_record
from vmn_exp.core.index_snapshot import IndexSnapshot, RowCache
from vmn_exp.core.index_store import IndexStore
from vmn_exp.core.index_sweep import (
    DEFAULT_FULL_SWEEP_SEC,
    METADATA_FILE,
    Sweep,
)
from vmn_exp.core.index_workers import load_new_records
from vmn_exp.core.log import experiment_row, load_log
from vmn_exp.core.status import load_run_state, observed_at_by_verstr

_LOGGER = logging.getLogger(__name__)
# Records a remote backend re-reads at once (each costs a few round trips).
_REMOTE_WORKERS = 16
_monotonic = time.monotonic


def _timestamp(meta):
    ts = meta.get("timestamp", "")
    return ts if isinstance(ts, str) else ""


class ExperimentIndex:
    """Incrementally maintained rows for one app of one storage backend."""

    def __init__(
        self, storage, app_name, cache_path=None, full_sweep_sec=DEFAULT_FULL_SWEEP_SEC
    ):
        self._storage = storage
        self.app_name = app_name
        self._cache_path = cache_path
        self._store = IndexStore(cache_path)
        self._sweep = Sweep(storage, app_name, full_sweep_sec)
        self._io = None  # the I/O helper process, once use_io_process() started it
        self._records = None
        self._order = None  # record keys in storage order
        self._stamps = None  # their timestamps, for bisecting new keys in
        self._reorder = ((), False)  # (new keys, whether one was re-described)
        self._rows = RowCache()
        self._snapshot = None
        self._lock = threading.Lock()
        self.generation = 0
        self.last_refresh_at = None  # monotonic start of the last refresh

    @property
    def full_sweep_sec(self):
        """Seconds between full listings; 0 (the default) lists fully every time."""
        return self._sweep.full_sweep_sec

    @full_sweep_sec.setter
    def full_sweep_sec(self, value):
        self._sweep.full_sweep_sec = value

    # -- refresh -------------------------------------------------------------

    def refresh(self):
        """Bring the index up to date with storage; returns self."""
        with self._lock:
            self._refresh_locked()
        return self

    def refresh_if_stale(self, max_age_sec):
        """The current snapshot, refreshed first if older than *max_age_sec*.

        While another thread refreshes, the current snapshot is returned at
        once — only the very first load waits for it.
        """
        snap = self._snapshot
        if snap is None:
            return self._first_load()
        if _monotonic() - self.last_refresh_at < max_age_sec:
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

    def _refresh_locked(self):
        started = _monotonic()
        try:
            self._refresh_from_storage(started)
        except Exception:
            # A listing's changes may have been taken but not applied.
            self._sweep.reset()
            raise
        self.last_refresh_at = started

    def _refresh_from_storage(self, started):
        if self._records is None:
            self._records = self._load_records()
        listing, removed = self._sweep.listing(self._records, started)

        # Unfinished claims and deleted records' leftovers have no metadata.
        work = [
            (key, names, self._records.get(key))
            for key, names in listing.items()
            if METADATA_FILE in names
        ]
        touched, new, redescribed = set(), [], False
        for key, record, dirty, moved, state_moved in self._refresh_and_persist(work, removed):
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
                self._sweep.track(key)
            if dirty:
                self._rows.pop(key, None)
            self._records[key] = _adopted(old, record, state_moved)
        for key in removed:
            del self._records[key]
            self._rows.pop(key, None)
            self._sweep.forget(key)
        # Only a new, removed or re-described record can move in the order.
        if new or removed or redescribed or self._order is None:
            self._reorder = (new, redescribed or bool(removed))
            self._order = self._sorted_keys()
        if touched or removed or self._snapshot is None:
            self.generation += 1
            self._snapshot = self._build_snapshot(None if removed else touched)

    def _load_records(self):
        return self._io.load() if self._io else self._store.load(self.app_name)

    def _refresh_and_persist(self, work, removed):
        """``(key, record or None, dirty, moved, state moved)`` per item of
        *work*, persisted with *removed*. The helper process answers None for
        a record it found unchanged."""
        if self._io is not None:
            return self._io.refresh(work, removed)
        direct_files = getattr(self._storage, "direct_files", None)
        direct = direct_files() if direct_files else self._storage
        results = self._refresh_records(work, direct)
        self._store.save(
            self.app_name,
            {key: record for key, record, dirty, _, _ in results if dirty},
            removed,
            {key: record for key, record, _, _, state_moved in results if state_moved},
        )
        return results

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
        is_remote = getattr(self._storage, "is_remote", None)
        if len(work) > 1 and is_remote and is_remote():
            with ThreadPoolExecutor(max_workers=_REMOTE_WORKERS) as pool:
                return list(pool.map(lambda w: self._refresh_one(*w, direct), work))
        return [self._refresh_one(*w, direct) for w in work]

    def _refresh_one(self, key, names, record, direct):
        return refresh_record(key, names, record, lambda *a: self._update(*a, direct))

    def _update(self, key, names, record, direct):
        """Refresh one record in place; ``(folded content changed, metadata
        changed, run state changed)``."""
        return update_record(self._storage, direct, self.app_name, key, names, record)

    def _sorted_keys(self):
        """Record keys in storage order (by timestamp, stably). New records
        are bisected into the current order; a first build, a re-described
        record (its timestamp may have moved) or a removal sorts them all."""
        new, resort = self._reorder
        if self._order is None or resort:
            keys = [k for k, r in self._records.items() if r["meta"] is not None]
            pairs = sorted(((_timestamp(self._records[k]["meta"]), k) for k in keys),
                           key=lambda pair: pair[0])
            self._stamps = [stamp for stamp, _ in pairs]
            return [key for _, key in pairs]
        order = list(self._order)
        for key in new:
            meta = self._records[key]["meta"]
            if meta is None:
                continue  # not an experiment
            stamp = _timestamp(meta)
            at = bisect.bisect_right(self._stamps, stamp)
            self._stamps.insert(at, stamp)
            order.insert(at, key)
        return order

    # -- snapshots -----------------------------------------------------------

    def _build_snapshot(self, touched=None):
        return self._rows.snapshot(
            self.app_name, self.generation, self._order or [], self._records, touched
        )

    def set_metric_schema(self, schema):
        """Summarize rows by the app's metrics *schema* (see
        :mod:`vmn_exp.core.metric_summary`). A different schema re-derives
        every row from its fold — no log is read again — as a new generation."""
        if (schema or None) == self._rows.schema:
            return  # the common case: no lock, so a request never waits on a refresh
        with self._lock:
            if self._rows.set_schema(schema) and self._snapshot is not None:
                self.generation += 1
                self._snapshot = self._build_snapshot()

    def snapshot(self):
        """The current :class:`IndexSnapshot`; the first call loads the index."""
        return self._snapshot or self._first_load()

    # -- copies of the current snapshot (call refresh() first) ---------------

    def rows(self, with_create_note=False):
        """``experiment_row`` dicts in storage order — fresh copies, ``idx`` set.

        ``with_create_note`` adds ``create_note``: the first ``create`` entry's
        note, which ``vmn-exp list`` shows for a run without a metadata note.
        """
        snap = self._snapshot
        return _row_copies(snap, with_create_note) if snap is not None else []

    def run_states(self):
        """``{verstr: raw run state or None}`` for the rows' experiments."""
        snap = self._snapshot
        return dict(snap.run_states) if snap is not None else {}


def _adopted(old, record, state_moved):
    """*record* as refreshed. A copy back from the helper process keeps
    *old*'s run state object unless it moved: readers diff generations by
    identity."""
    if old is not None and record is not old and not state_moved:
        record["run_state"] = old["run_state"]
    return record


def _row_copies(snap, with_create_note):
    if with_create_note:
        notes = snap.create_notes
        return [dict(row, create_note=notes[row["verstr"]]) for row in snap.rows]
    return [dict(row) for row in snap.rows]


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
    if cache_path is None:
        path_of = getattr(storage, "index_cache_path", None)
        cache_path = path_of(app_name) if path_of else None
    identity_of = getattr(storage, "cache_identity", None)
    identity = identity_of() if identity_of else None
    if identity is None:
        return ExperimentIndex(storage, app_name, cache_path)
    key = (identity, app_name, cache_path)
    with _SHARED_LOCK:
        index = _SHARED.get(key)
        if index is None:
            index = _SHARED[key] = ExperimentIndex(storage, app_name, cache_path)
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
    rows = []
    for idx, meta in enumerate(storage.list_snapshots(app_name), 1):
        log = read_log(storage, app_name, meta["verstr"])
        row = experiment_row(idx, meta, log, schema=schema)
        if with_create_note:
            create = next((e for e in log if e.get("type") == "create"), None)
            row["create_note"] = (create or {}).get("note")
        rows.append(row)
    if read_run_state is None:
        return rows, {}
    states = {r["verstr"]: read_run_state(storage, app_name, r["verstr"]) for r in rows}
    return rows, states


def direct_snapshot(storage, app_name, schema=None):
    """An :class:`IndexSnapshot` (generation 0) built by reading every record."""
    rows, states = direct_rows(storage, app_name, with_create_note=True, schema=schema)
    notes = {row["verstr"]: row.pop("create_note") for row in rows}
    observed = observed_at_by_verstr(storage, app_name, states)
    return IndexSnapshot.build(app_name, 0, rows, states, notes, observed)


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
    """The shared index's :class:`IndexSnapshot`, refreshed when older than
    *max_age_sec* — or, with *wait*, refreshed now even if another thread's
    refresh has to finish first. *full_sweep_sec* is passed on to
    :func:`shared_index`; a *schema* other than None becomes the index's
    metrics schema (:meth:`ExperimentIndex.set_metric_schema`). If the index
    fails, ``fallback(storage, app_name, schema)`` answers instead; a None
    *fallback* returns None."""
    try:
        index = shared_index(storage, app_name, cache_path, full_sweep_sec)
        if schema is not None:
            index.set_metric_schema(schema)
        if wait:
            return index.refresh().snapshot()
        return index.refresh_if_stale(max_age_sec)
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
