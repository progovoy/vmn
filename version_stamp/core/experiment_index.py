#!/usr/bin/env python3
"""An incremental index of an app's experiments: leaderboard rows without
re-reading every log whenever anything changes.

Which records a refresh looks at is :mod:`experiment_index_sweep`'s call:
normally the new and live ones from a names-only listing, every
``full_sweep_sec`` all of them. Of those only what moved is read: a new record
is loaded, a changed ``metadata.yml`` re-read, a grown log read from where it
was last read up to (:mod:`experiment_index_logs`), a rewritten
``run_state.yml`` — a heartbeat — re-read on its own. The folded state
persists in SQLite (:mod:`experiment_index_store`), so a new process starts
warm; a heartbeat there rewrites only its small run-state row.

Readers get an immutable :class:`IndexSnapshot` per ``generation`` (bumped by
anything visible, run states included) that never takes the index lock or
touches storage. Its rows are exactly ``experiment_row``'s; status is derived
from its run states on every read, since it depends on the clock.

Storage is duck-typed (``list_files``, ``load_file``, and optionally
``list_record_names``/``list_files(keys=)``/``direct_files``/``read_file_from``/
``index_cache_path``/``cache_identity``); like the rest of ``core`` this
imports nothing from ``cli``, ``ui`` or ``exp``.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from version_stamp.core.experiment_fold import new_fold
from version_stamp.core.experiment_index_logs import log_signatures, update_logs
from version_stamp.core.experiment_index_snapshot import IndexSnapshot, RowCache
from version_stamp.core.experiment_index_store import IndexStore
from version_stamp.core.experiment_index_sweep import (
    DEFAULT_FULL_SWEEP_SEC,
    METADATA_FILE,
    Sweep,
)
from version_stamp.core.experiment_log import experiment_row, load_log
from version_stamp.core.experiment_status import RUN_STATE_FILE, load_run_state
from version_stamp.core.utils import parse_record_metadata

_LOGGER = logging.getLogger(__name__)
# Records a remote backend re-reads at once (each costs a few round trips).
_REMOTE_WORKERS = 16
_monotonic = time.monotonic


def _new_record():
    return {
        "meta_sig": None,
        "meta": None,
        "logs": {},
        "counts": {},
        "fold": new_fold(),
        "rs_sig": None,
        "run_state": None,
    }


def _sig(value):
    return list(value) if value is not None else None


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
        self._store = IndexStore(cache_path)
        self._sweep = Sweep(storage, app_name, full_sweep_sec)
        self._records = None
        self._order = None  # record keys in storage order, rebuilt on change
        self._rows = RowCache()
        self._snapshot = None
        self._lock = threading.Lock()
        self.generation = 0
        self.last_refresh_at = None  # monotonic start of the last refresh

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

    def _refresh_locked(self):
        started = _monotonic()
        if self._records is None:
            self._records = self._store.load(self.app_name)
        direct_files = getattr(self._storage, "direct_files", None)
        direct = direct_files() if direct_files else None
        listing, present = self._sweep.listing(self._records, started)

        # Unfinished claims and deleted records' leftovers have no metadata.
        work = [
            (key, names, self._records.get(key))
            for key, names in listing.items()
            if METADATA_FILE in names
        ]
        changed, states, reorder = {}, {}, self._order is None
        for key, record, dirty, moved, state_moved in self._refresh_records(work, direct):
            if (dirty or state_moved) and key in self._records:
                self._sweep.touch(key, started)
            if dirty:
                self._records[key] = changed[key] = record
                self._rows.pop(key, None)
            if state_moved:
                self._records[key] = states[key] = record
            reorder = reorder or moved
        removed = [key for key in self._records if key not in present]
        for key in removed:
            del self._records[key]
            self._rows.pop(key, None)
            self._sweep.forget(key)
        # Only a new, removed or re-described record can move in the order.
        if reorder or removed:
            self._order = self._sorted_keys()
        self._store.save(self.app_name, changed, removed, states)
        if changed or states or removed or self._snapshot is None:
            self.generation += 1
            self._snapshot = self._build_snapshot()
        self.last_refresh_at = started

    def _refresh_records(self, work, direct):
        """``(key, record, dirty, moved, state moved)`` per ``(key, names,
        record)`` in *work*.

        A remote backend's records are re-read concurrently: each costs a few
        round trips, and a cold index on S3 would otherwise pay them serially.
        """
        is_remote = getattr(self._storage, "is_remote", None)
        if len(work) > 1 and is_remote and is_remote():
            with ThreadPoolExecutor(max_workers=_REMOTE_WORKERS) as pool:
                return list(pool.map(lambda w: self._refresh_one(*w, direct), work))
        return [self._refresh_one(*w, direct) for w in work]

    def _refresh_one(self, key, names, record, direct):
        fresh = record is None
        record = _new_record() if fresh else record
        dirty, meta_changed, state_changed = self._update(key, names, record, direct)
        return key, record, dirty, fresh or meta_changed, state_changed

    def _update(self, key, names, record, direct):
        """Refresh one record in place; ``(folded content changed, metadata
        changed, run state changed)``."""
        dirty = meta_changed = False
        meta_sig = _sig(names[METADATA_FILE])
        if record["meta_sig"] != meta_sig:
            record["meta"] = self._load_meta(key)
            record["meta_sig"] = meta_sig
            dirty = meta_changed = True
        sigs = log_signatures(names)
        if update_logs(record, self._storage, direct, self.app_name, key, sigs):
            dirty = True
        return dirty, meta_changed, self._update_run_state(key, names, record)

    def _update_run_state(self, key, names, record):
        rs_sig = _sig(names.get(RUN_STATE_FILE))
        if record["rs_sig"] == rs_sig:
            return False
        record["run_state"] = (
            load_run_state(self._storage, self.app_name, key) if rs_sig else None
        )
        record["rs_sig"] = rs_sig
        return True

    def _load_meta(self, key):
        # The same rule list_snapshots applies: legacy verinfo files share the tree.
        raw = self._storage.load_file(self.app_name, key, METADATA_FILE)
        return parse_record_metadata(raw)

    def _sorted_keys(self):
        keys = [k for k, r in self._records.items() if r["meta"] is not None]
        return sorted(keys, key=lambda k: _timestamp(self._records[k]["meta"]))

    # -- snapshots -----------------------------------------------------------

    def _build_snapshot(self):
        return self._rows.snapshot(
            self.app_name, self.generation, self._order or [], self._records
        )

    def snapshot(self):
        """The current :class:`IndexSnapshot`; the first call loads the index."""
        return self._snapshot or self._first_load()

    # -- copies of the current snapshot (call refresh() first) ---------------

    def rows(self, with_create_note=False):
        """``experiment_row`` dicts in storage order — fresh copies, ``idx`` set.

        ``with_create_note`` adds ``create_note``: the first ``create`` entry's
        note, which ``vmn exp list`` shows for a run without a metadata note.
        """
        snap = self._snapshot
        if snap is None:
            return []
        if with_create_note:
            notes = snap.create_notes
            return [dict(row, create_note=notes[row["verstr"]]) for row in snap.rows]
        return [dict(row) for row in snap.rows]

    def run_states(self):
        """``{verstr: raw run state or None}`` for the rows' experiments."""
        snap = self._snapshot
        return dict(snap.run_states) if snap is not None else {}


# ---------------------------------------------------------------------------
# Process-wide access with a direct fallback
# ---------------------------------------------------------------------------

_SHARED = {}
_SHARED_LOCK = threading.Lock()


def shared_index(storage, app_name, cache_path=None):
    """The process-wide index for *storage*'s *app_name* data.

    Keyed by the backend's ``cache_identity()`` so equivalent storage objects
    share one warm index. Persisted at *cache_path* when given (the ui keeps its
    own under the server data dir), else at the backend's ``index_cache_path``.
    """
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
):
    """``(rows, run_states)`` by reading every record — the index's reference.

    *read_log* / *read_run_state* are the caller's loaders; a None
    *read_run_state* skips the run states (``{}``).
    """
    rows = []
    for idx, meta in enumerate(storage.list_snapshots(app_name), 1):
        log = read_log(storage, app_name, meta["verstr"])
        row = experiment_row(idx, meta, log)
        if with_create_note:
            create = next((e for e in log if e.get("type") == "create"), None)
            row["create_note"] = (create or {}).get("note")
        rows.append(row)
    if read_run_state is None:
        return rows, {}
    states = {r["verstr"]: read_run_state(storage, app_name, r["verstr"]) for r in rows}
    return rows, states


def indexed_snapshot(storage, app_name, cache_path=None, max_age_sec=0):
    """The shared index's :class:`IndexSnapshot`, refreshed when older than
    *max_age_sec*; one built by a direct read if the index fails."""
    try:
        index = shared_index(storage, app_name, cache_path)
        return index.refresh_if_stale(max_age_sec)
    except Exception:
        _LOGGER.debug("Experiment index unavailable; reading directly", exc_info=True)
        rows, states = direct_rows(storage, app_name, with_create_note=True)
        notes = {row["verstr"]: row.pop("create_note") for row in rows}
        return IndexSnapshot.build(app_name, 0, rows, states, notes)


def indexed_rows(storage, app_name, with_create_note=False, cache_path=None):
    """``(rows, run_states)`` through the shared index; directly if it fails."""
    try:
        index = shared_index(storage, app_name, cache_path).refresh()
        return index.rows(with_create_note), index.run_states()
    except Exception:
        _LOGGER.debug("Experiment index unavailable; reading directly", exc_info=True)
        return direct_rows(storage, app_name, with_create_note)
