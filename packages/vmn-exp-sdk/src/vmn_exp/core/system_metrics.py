#!/usr/bin/env python3
"""The ``sys_*`` system metrics: off the index's lean rows.

``vmn-exp run`` and the SDK sample CPU, memory and GPU use on every heartbeat
by default (:mod:`vmn_exp.sdk.sysmetrics`), so every run carries them, each
logged many times. Boards built from the lean rows — leaderboard rows,
facets, sorts, job rollups — leave them out; the snapshot keeps them per run
beside the rows (:meth:`~vmn_exp.core.index_snapshot.IndexSnapshot.metrics_of`)
for what serves a run's metrics: row copies, queries, chart columns, compare.
"""
SYSTEM_PREFIX = "sys_"


def is_system_metric(name):
    return name.startswith(SYSTEM_PREFIX)


def split_system(values):
    """``(the rest, the system metrics)`` of *values* ``{metric: value}``."""
    if not any(is_system_metric(name) for name in values):
        return values, {}
    rest, system = {}, {}
    for name, value in values.items():
        (system if is_system_metric(name) else rest)[name] = value
    return rest, system
