#!/usr/bin/env python3
"""Whole-set chart data: one array per requested key over the ordered rows.

A chart of every filtered run needs a few values per run, not whole rows, so
``.../experiments-columns`` answers ``{verstrs, idx, columns, total}`` with
each column aligned to ``verstrs``.
"""
from version_stamp.core.experiment_log import _sortable

COLUMNS_LIMIT = 20000
MAX_COLUMNS_LIMIT = 50000
_FIELDS = ("timestamp", "status", "branch")


def clamp_columns_limit(limit):
    if limit is None:
        return COLUMNS_LIMIT
    return max(0, min(int(limit), MAX_COLUMNS_LIMIT))


def _metric(name):
    def get(row):
        value = row["metrics"].get(name)
        return value if _sortable(value) else None

    return get


def _param(name):
    return lambda row: row["params"].get(name)


def _name(row):
    return row.get("name") or row.get("note")


def column_getter(key):
    """The value reader of *key*; ValueError for a key no row can answer."""
    group, _, name = key.partition(".")
    if group == "metrics" and name:
        return _metric(name)
    if group == "params" and name:
        return _param(name)
    if key == "name":
        return _name
    if key in _FIELDS:
        return lambda row: row.get(key)
    raise ValueError(
        f"Unknown column '{key}' (use metrics.<k>, params.<k>, timestamp, status, branch or name)"
    )


def columns_payload(rows, keys, total):
    getters = {key: column_getter(key) for key in keys}
    return {
        "verstrs": [row["verstr"] for row in rows],
        "idx": [row["idx"] for row in rows],
        "columns": {key: [get(row) for row in rows] for key, get in getters.items()},
        "total": total,
    }
