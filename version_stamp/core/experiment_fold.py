#!/usr/bin/env python3
"""The leaderboard fold of :mod:`version_stamp.core.experiment_log`, incrementally.

``experiment_row`` folds a merged log: the legacy ``log.yml`` entries, then each
writer's entries (writers by name, in file order), stably sorted by timestamp —
so every value it reports is the one carried by the *last* entry in that order.
That order is a total key, ``(timestamp, writer, position in writer)``, so the
same row falls out of keeping, per field, the value with the greatest key seen.
Entries can then arrive in any chunks, per writer, in file order: a log that
grew by one line costs one line, not a re-read of the whole log.

A fold is plain JSON-able data, so the experiment index can persist it as is.
Pure: no storage, no clock.
"""
from version_stamp.core.experiment_log import (
    _foldable_param,
    entry_params,
    experiment_row,
)


def new_fold():
    """The fold of an empty log."""
    return {"params": {}, "metrics": {}, "last_metric": None, "create_note": None}


def _sort_key(entry, writer, position):
    ts = entry.get("timestamp", "")
    return [ts if isinstance(ts, str) else "", writer, position]


def _keep_latest(values, name, value, key):
    current = values.get(name)
    if current is None or key >= current[1]:
        values[name] = [value, key]


def _apply(fold, entry, key):
    etype = entry.get("type")
    for name, value in entry_params(entry).items():
        _keep_latest(fold["params"], name, value, key)
        number = _foldable_param(value)
        if number is not None:
            _keep_latest(fold["metrics"], name, number, key)
    if etype == "metrics":
        for name, value in (entry.get("values") or {}).items():
            _keep_latest(fold["metrics"], name, value, key)
        if fold["last_metric"] is None or key >= fold["last_metric"][1]:
            fold["last_metric"] = [entry.get("timestamp"), key]
    elif etype == "create":
        if fold["create_note"] is None or key < fold["create_note"][1]:
            fold["create_note"] = [entry.get("note"), key]


def apply_entries(fold, writer, first_position, entries):
    """Fold *entries* — *writer*'s log from *first_position* on — into *fold*."""
    for offset, entry in enumerate(entries):
        if isinstance(entry, dict):
            _apply(fold, entry, _sort_key(entry, writer, first_position + offset))
    return fold


def fold_row(idx, meta, fold, with_create_note=False):
    """The ``experiment_row`` for *meta* whose log folded into *fold*.

    ``with_create_note`` adds the first ``create`` entry's note (what
    ``vmn exp list`` shows for a run without a metadata note).
    """
    row = experiment_row(idx, meta, [])
    row["params"] = {name: value for name, (value, _) in fold["params"].items()}
    row["metrics"] = {name: value for name, (value, _) in fold["metrics"].items()}
    row["last_metric_at"] = fold["last_metric"][0] if fold["last_metric"] else None
    if with_create_note:
        row["create_note"] = fold["create_note"][0] if fold["create_note"] else None
    return row
