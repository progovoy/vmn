#!/usr/bin/env python3
"""Whole-set chart data: one array per requested key over the ordered rows.

A chart of every filtered run needs a few values per run, not whole rows, so
``.../experiments-columns`` answers ``{verstrs, idx, columns, total}`` with
each column aligned to ``verstrs``. A ``metrics.sys_*`` column reads the
``sys_*`` metrics the snapshot keeps off its rows (*system_of*), an
``up.<field>`` column the rows' ancestors in the snapshot (plan 28 N1).
"""
from vmn_exp.core.system_metrics import is_system_metric
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.leaderboard_group_fields import check_group, key_of, up_node, value_of

COLUMNS_LIMIT = 20000
MAX_COLUMNS_LIMIT = 50000
_FIELDS = ("timestamp", "status", "branch")
# ``group:<field>``: a row's group key on the board grouped by <field>.
GROUP_PREFIX = "group:"


def clamp_columns_limit(limit):
    if limit is None:
        return COLUMNS_LIMIT
    return max(0, min(int(limit), MAX_COLUMNS_LIMIT))


def _metric(name, system_of):
    def get(row):
        metrics = system_of(row["verstr"]) if is_system_metric(name) else row["metrics"]
        value = metrics.get(name)
        return value if is_finite_number(value) else None

    return get


def _param(name):
    return lambda row: row["params"].get(name)


def _name(row):
    return row.get("name") or row.get("note")


def column_getter(key, system_of=None, snapshot=None):
    """The value reader of *key*; ValueError for a key no row can answer.
    *system_of(verstr)*: a run's ``sys_*`` metrics (none by default);
    *snapshot*: whose ancestors an ``up`` key reads."""
    if key.startswith(GROUP_PREFIX):
        return key_of(check_group(key[len(GROUP_PREFIX):]), snapshot)
    if up_node(key):
        return value_of(key, snapshot)
    group, _, name = key.partition(".")
    if group == "metrics" and name:
        return _metric(name, system_of or (lambda verstr: {}))
    if group == "params" and name:
        return _param(name)
    if key == "name":
        return _name
    if key in _FIELDS:
        return lambda row: row.get(key)
    raise ValueError(
        f"Unknown column '{key}' (use metrics.<k>, params.<k>, up.<field>, group:<field>, "
        "timestamp, status, branch or name)"
    )


def columns_payload(rows, keys, total, system_of=None, snapshot=None):
    getters = {key: column_getter(key, system_of, snapshot) for key in keys}
    return {
        "verstrs": [row["verstr"] for row in rows],
        "idx": [row["idx"] for row in rows],
        "columns": {key: [get(row) for row in rows] for key, get in getters.items()},
        "total": total,
    }
