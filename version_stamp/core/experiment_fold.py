#!/usr/bin/env python3
"""The leaderboard fold: the one place that turns log entries into a row.

A fold keeps, per field, the value carried by the entry with the greatest key.
:func:`fold_log` keys a log by list position — the last entry wins, which is
what ``experiment_row`` has always meant. The experiment index keys entries by
``(timestamp, writer, position in writer)`` instead: that is the order the
merged log is in (the legacy ``log.yml`` entries, then each writer's in file
order, stably sorted by timestamp), so entries can arrive in any chunks, per
writer, and still fold to the same row — a log that grew by one line costs one
line, not a re-read of the whole log.

A fold is plain JSON-able data, so the experiment index can persist it as is.
Pure: no storage, no clock.
"""
import math


def entry_params(entry):
    """Params carried by a log entry.

    `create` records params up front, `run.log_params()` mid-run.
    """
    if entry.get("type") in ("create", "params"):
        return entry.get("params") or {}
    return {}


def _foldable_param(value):
    """A param as a metric value: a finite number (bools fold as 1.0/0.0) — else None.

    ``missing=nan`` (xgboost's default) is a setting, not a measurement;
    folding it in made every such run carry a NaN "metric".
    """
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def new_fold():
    """The fold of an empty log."""
    return {
        "params": {},
        "metrics": {},
        "tags": {},
        "last_metric": None,
        "create_note": None,
    }


def entry_tags(entry):
    """``(set, removed)`` tag changes carried by a log entry.

    A ``tags`` entry sets and removes; a ``create`` entry may seed tags from a
    notes file, as a mapping or a list of bare labels.
    """
    etype = entry.get("type")
    if etype == "tags":
        return entry.get("set") or {}, entry.get("remove") or []
    if etype == "create":
        seeded = entry.get("tags")
        if isinstance(seeded, dict):
            return {str(k): str(v) for k, v in seeded.items()}, []
        if isinstance(seeded, list):
            return {str(k): "" for k in seeded}, []
    return {}, []


def _sort_key(entry, writer, position):
    ts = entry.get("timestamp", "")
    return [ts if isinstance(ts, str) else "", writer, position]


def _keep_latest(values, name, value, key):
    current = values.get(name)
    if current is None or key >= current[1]:
        values[name] = [value, key]


def _apply_tags(fold, entry, key):
    tags = fold.setdefault("tags", {})
    changed, removed = entry_tags(entry)
    for name, value in changed.items():
        _keep_latest(tags, name, value, key)
    for name in removed:
        _keep_latest(tags, name, None, key)  # a tombstone: removal is a write too


def _apply(fold, entry, key):
    etype = entry.get("type")
    _apply_tags(fold, entry, key)
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


def fold_log(log, fold=None, start=0):
    """The fold of *log* taken as given: every value is the last one in list order.

    With *fold* — the fold of the *start* entries before *log* — the entries
    are folded into it, so a log that grew folds only its new entries.
    """
    fold = new_fold() if fold is None else fold
    for position, entry in enumerate(log, start):
        if isinstance(entry, dict):
            _apply(fold, entry, [position])
    return fold


def fold_values(fold, field):
    """``{name: value}`` of a fold's ``params`` or ``metrics``."""
    return {name: value for name, (value, _) in fold[field].items()}


def fold_tags(fold):
    """``{name: value}`` of the tags a fold holds (removed ones left out)."""
    return {
        name: value
        for name, (value, _) in fold.get("tags", {}).items()
        if value is not None
    }


def fold_last_metric_at(fold):
    return fold["last_metric"][0] if fold["last_metric"] else None


def fold_row(idx, meta, fold, with_create_note=False):
    """The leaderboard row for *meta* whose log folded into *fold*.

    *idx* is the 1-based storage index — what ``vmn exp show <app> -v @N``
    resolves — and is assigned before any sort so it sticks to the row.
    ``params`` carries every param verbatim; ``metrics`` stays numeric-only (with
    the numeric params folded in), because sorting and charting depend on that.
    ``with_create_note`` adds the first ``create`` entry's note (what
    ``vmn exp list`` shows for a run without a metadata note).
    """
    row = {
        "idx": idx,
        "verstr": meta["verstr"],
        "code_verstr": meta.get("code_verstr", meta["verstr"]),
        "timestamp": meta.get("timestamp"),
        "note": meta.get("note"),
        "branch": meta.get("branch"),
        "base_version": meta.get("base_version"),
        "user_meta": meta.get("user_meta"),
        "name": meta.get("name"),
        "archived": bool(meta.get("archived", False)),
        "tags": fold_tags(fold),
        "params": fold_values(fold, "params"),
        "metrics": fold_values(fold, "metrics"),
        "parent": meta.get("parent"),
        "last_metric_at": fold_last_metric_at(fold),
    }
    if with_create_note:
        row["create_note"] = fold["create_note"][0] if fold["create_note"] else None
    return row
