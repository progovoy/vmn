#!/usr/bin/env python3
"""Snapshots built by reading every record, without the index: the
reference :mod:`vmn_exp.core.index` falls back to (``direct_rows`` itself
stays there, since tests patch it on that module)."""
from vmn_exp.core.fold import fold_log
from vmn_exp.core.index_snapshot import IndexSnapshot, new_side_tables, put_side_tables
from vmn_exp.core.index_views import lean_row
from vmn_exp.core.log import load_log
from vmn_exp.core.status import load_run_state, observed_at_by_verstr


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
    :func:`~vmn_exp.core.index.indexed_snapshot`'s."""

    def run_states(rows):
        states = _run_states(storage, app_name, rows, read_run_state)
        return states, observed_at_by_verstr(storage, app_name, states)

    folds = _direct_folds(storage, app_name, read_log)
    return snapshot_of_folds(app_name, folds, run_states).summarized(schema)
