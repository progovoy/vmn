#!/usr/bin/env python3
"""An incremental index of an app's experiments: leaderboard rows without
re-reading every log whenever anything changes.

Each refresh asks the storage for one listing of every record file's
``(size, mtime)`` and then touches only what moved: a new record is loaded, a
changed ``metadata.yml`` re-read, a grown log read from where it was last read
up to (:mod:`experiment_index_logs`), a rewritten ``run_state.yml`` — a
heartbeat — re-read on its own. The folded state persists in SQLite
(:mod:`experiment_index_store`), so a new process starts warm.

Rows are exactly :func:`version_stamp.core.experiment_log.experiment_row`'s.
Status is not in them: it depends on the clock, so callers derive it from
:meth:`ExperimentIndex.run_states` on every read.

Storage is duck-typed (``list_files``, ``load_file``, and optionally
``direct_files``/``read_file_from``/``index_cache_path``/``cache_identity``);
like the rest of ``core`` this imports nothing from ``cli``, ``ui`` or ``exp``.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from version_stamp.core.experiment_fold import fold_row, new_fold
from version_stamp.core.experiment_index_logs import log_signatures, update_logs
from version_stamp.core.experiment_index_store import IndexStore
from version_stamp.core.experiment_log import experiment_row, load_log
from version_stamp.core.experiment_status import RUN_STATE_FILE, load_run_state
from version_stamp.core.utils import parse_record_metadata

METADATA_FILE = "metadata.yml"

_LOGGER = logging.getLogger(__name__)
# Records a remote backend re-reads at once (each costs a few round trips).
_REMOTE_WORKERS = 16


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

    def __init__(self, storage, app_name, cache_path=None):
        self._storage = storage
        self.app_name = app_name
        self._store = IndexStore(cache_path)
        self._records = None
        self._order = None  # record keys in storage order, rebuilt on change
        self._rows = {}  # key -> materialized row (idx filled on read)
        self._lock = threading.Lock()

    # -- refresh -------------------------------------------------------------

    def refresh(self):
        """Bring the index up to date with storage; returns self."""
        with self._lock:
            if self._records is None:
                self._records = self._store.load(self.app_name)
            direct_files = getattr(self._storage, "direct_files", None)
            direct = direct_files() if direct_files else None
            listing = self._storage.list_files(self.app_name)

            # Unfinished claims and deleted records' leftovers have no metadata.
            work = [
                (key, names, self._records.get(key))
                for key, names in listing.items()
                if METADATA_FILE in names
            ]
            changed, reorder = {}, self._order is None
            for key, record, dirty, moved in self._refresh_records(work, direct):
                if dirty:
                    self._records[key] = changed[key] = record
                    self._rows.pop(key, None)
                reorder = reorder or moved
            removed = [
                key
                for key in self._records
                if METADATA_FILE not in listing.get(key, {})
            ]
            for key in removed:
                del self._records[key]
                self._rows.pop(key, None)
            # Only a new, removed or re-described record can move in the order.
            if reorder or removed:
                self._order = self._sorted_keys()
            self._store.save(self.app_name, changed, removed)
        return self

    def _refresh_records(self, work, direct):
        """``(key, record, dirty, moved)`` per ``(key, names, record)`` in *work*.

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
        dirty, meta_changed = self._update(key, names, record, direct)
        return key, record, dirty, fresh or meta_changed

    def _update(self, key, names, record, direct):
        """Refresh one record in place; ``(changed at all, metadata changed)``."""
        dirty = meta_changed = False
        meta_sig = _sig(names[METADATA_FILE])
        if record["meta_sig"] != meta_sig:
            record["meta"] = self._load_meta(key)
            record["meta_sig"] = meta_sig
            dirty = meta_changed = True
        sigs = log_signatures(names)
        if update_logs(record, self._storage, direct, self.app_name, key, sigs):
            dirty = True
        rs_sig = _sig(names.get(RUN_STATE_FILE))
        if record["rs_sig"] != rs_sig:
            record["run_state"] = (
                load_run_state(self._storage, self.app_name, key) if rs_sig else None
            )
            record["rs_sig"] = rs_sig
            dirty = True
        return dirty, meta_changed

    def _load_meta(self, key):
        # The same rule list_snapshots applies: legacy verinfo files share the tree.
        raw = self._storage.load_file(self.app_name, key, METADATA_FILE)
        return parse_record_metadata(raw)

    def _sorted_keys(self):
        keys = [k for k, r in self._records.items() if r["meta"] is not None]
        return sorted(keys, key=lambda k: _timestamp(self._records[k]["meta"]))

    # -- reads (call refresh() first) ----------------------------------------

    def _row(self, key):
        row = self._rows.get(key)
        if row is None:
            record = self._records[key]
            row = self._rows[key] = fold_row(0, record["meta"], record["fold"], True)
        return row

    def rows(self, with_create_note=False):
        """``experiment_row`` dicts in storage order — fresh copies, ``idx`` set.

        ``with_create_note`` adds ``create_note``: the first ``create`` entry's
        note, which ``vmn exp list`` shows for a run without a metadata note.
        """
        with self._lock:
            out = []
            for idx, key in enumerate(self._order or [], 1):
                row = dict(self._row(key))
                row["idx"] = idx
                if not with_create_note:
                    row.pop("create_note", None)
                out.append(row)
            return out

    def run_states(self):
        """``{verstr: raw run state or None}`` for the rows' experiments."""
        with self._lock:
            return {
                self._records[k]["meta"]["verstr"]: self._records[k]["run_state"]
                for k in self._order or []
            }


# ---------------------------------------------------------------------------
# Process-wide access with a direct fallback
# ---------------------------------------------------------------------------

_SHARED = {}
_SHARED_LOCK = threading.Lock()


def shared_index(storage, app_name):
    """The process-wide index for *storage*'s *app_name* data.

    Keyed by the backend's ``cache_identity()`` so equivalent storage objects
    share one warm index; persisted at its ``index_cache_path`` when it has one.
    """
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


def direct_rows(storage, app_name, with_create_note=False):
    """``(rows, run_states)`` by reading every record — the index's reference."""
    rows = []
    for idx, meta in enumerate(storage.list_snapshots(app_name), 1):
        log = load_log(storage, app_name, meta["verstr"])
        row = experiment_row(idx, meta, log)
        if with_create_note:
            create = next((e for e in log if e.get("type") == "create"), None)
            row["create_note"] = (create or {}).get("note")
        rows.append(row)
    states = {r["verstr"]: load_run_state(storage, app_name, r["verstr"]) for r in rows}
    return rows, states


def indexed_rows(storage, app_name, with_create_note=False):
    """``(rows, run_states)`` through the shared index; directly if it fails."""
    try:
        index = shared_index(storage, app_name).refresh()
        return index.rows(with_create_note), index.run_states()
    except Exception:
        _LOGGER.debug("Experiment index unavailable; reading directly", exc_info=True)
        return direct_rows(storage, app_name, with_create_note)
