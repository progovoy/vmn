#!/usr/bin/env python3
"""Bring one :mod:`experiment_index` record up to date with its files.

A record is plain data — its metadata, its folded log, its run state and the
file signatures they were read at — so a worker process can load it with the
same code as the index (:mod:`experiment_index_workers`) and hand it back.
"""
from vmn_exp._base import parse_record_metadata
from vmn_exp.core.fold import new_fold
from vmn_exp.core.index_logs import log_signatures, update_logs
from vmn_exp.core.index_sweep import METADATA_FILE
from vmn_exp.core.status import RUN_STATE_FILE, load_run_state


def new_record():
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


def refresh_record(key, names, record, update):
    """``(record, dirty, moved, state moved)`` for *record* (None: a new one)
    refreshed in place by *update* ``(key, names, record)`` — normally
    :func:`update_record` — to the files *names*.

    *moved*: it is new or its metadata changed, so it may move in the order.
    """
    fresh = record is None
    record = new_record() if fresh else record
    dirty, meta_changed, state_moved = update(key, names, record)
    return record, dirty, fresh or meta_changed, state_moved


def update_record(storage, direct, app_name, key, names, record):
    """Refresh *record* in place to the files *names* ``{filename: signature}``;
    ``(folded content changed, metadata changed, run state changed)``."""
    dirty = meta_changed = False
    meta_sig = _sig(names[METADATA_FILE])
    if record["meta_sig"] != meta_sig:
        record["meta"] = _load_meta(storage, app_name, key)
        record["meta_sig"] = meta_sig
        dirty = meta_changed = True
    if update_logs(record, storage, direct, app_name, key, log_signatures(names)):
        dirty = True
    return dirty, meta_changed, _update_run_state(storage, app_name, key, names, record)


def listed_unchanged(record, names):
    """Whether *names* are exactly the files *record* was last read at, so
    :func:`update_record` would find nothing to do."""
    return (
        record["meta_sig"] == _sig(names[METADATA_FILE])
        and record["rs_sig"] == _sig(names.get(RUN_STATE_FILE))
        and {n: state["sig"] for n, state in record["logs"].items()} == log_signatures(names)
    )


def _update_run_state(storage, app_name, key, names, record):
    rs_sig = _sig(names.get(RUN_STATE_FILE))
    if record["rs_sig"] == rs_sig:
        return False
    record["run_state"] = load_run_state(storage, app_name, key) if rs_sig else None
    record["rs_sig"] = rs_sig
    return True


def _load_meta(storage, app_name, key):
    # The same rule list_snapshots applies: legacy verinfo files share the tree.
    return parse_record_metadata(storage.load_file(app_name, key, METADATA_FILE))
