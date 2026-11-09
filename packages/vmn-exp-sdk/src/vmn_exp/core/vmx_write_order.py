#!/usr/bin/env python3
"""A ``.vmx`` footer's keys in write order, however old the file.

A footer marked :data:`~vmn_exp.core.metric_index_layout.WRITE_ORDER`
carries each key's first and last write, true time bounds ``t`` and restart
point ``r`` (:mod:`~vmn_exp.core.metric_index_file`). An older one took its
``first``/``last`` and ``t`` after sorting the points by step, and has no
``r``: for its stepped keys these are read from the columns — the steps and
timestamps once, the values of the two ends — so the fold reads it right
(a step-less key was sorted by time already). Nothing is written back.
"""
from vmn_exp.core.fold_blocks import footer_entries
from vmn_exp.core.metric_index_layout import WRITE_ORDER
from vmn_exp.core.step_restart import restart_point


def indexed_entries(reader):
    """The block-header shaped entries of *reader*'s keys, in write order."""
    entries = footer_entries(reader.footer)
    if reader.footer.get("order") == WRITE_ORDER:
        return entries
    return [_in_write_order(reader, entry) if entry["has_step"] else entry
            for entry in entries]


def _in_write_order(reader, entry):
    key = entry["k"]
    steps, ts = reader.column(key, "steps"), reader.column(key, "ts")
    order = sorted(range(len(ts)), key=ts.__getitem__)  # ties stay in stored order
    first, last = order[0], order[-1]
    out = dict(entry, first=_point(reader, key, steps, ts, first),
               last=_point(reader, key, steps, ts, last), t=[ts[first], ts[last]])
    restart = restart_point(steps[i] for i in order)
    if restart is not None:
        out["r"] = restart
    return out


def _point(reader, key, steps, ts, i):
    return [reader.column(key, "values", i, i + 1)[0], steps[i], ts[i]]
