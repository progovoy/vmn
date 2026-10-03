#!/usr/bin/env python3
"""The leaderboard fold of metric streams (plan 12 §5.3): per block header
(or ``.vmx`` footer) summary, not per point.

A point folds at the key ``(timestamp, writer, position)``, its position
counting the writer's stream points (a block's keys share its positions).
Each key summary carries its first and last points and its finite
``{n, sum, parts, min, max}``, so last/first/min/max/count/sum combine
exactly. A block a known rewind may hide points of folds point by point
instead (:func:`may_be_rewound`), from its decoded body.
Pure: no storage.
"""
from vmn_exp.core.fold import _apply, _keep_latest
from vmn_exp.core.metric_entries import points_to_entries
from vmn_exp.core.metric_stream import base_key
from vmn_exp.core.metric_summary import track_block, track_extrema
from vmn_exp.core.metric_time import iso_to_us, us_to_iso


def footer_entries(footer):
    """A ``.vmx`` footer's keys in the block-header shape."""
    return [dict(meta["summary"], k=name, n=meta["n"], has_step=meta["has_step"],
                 s=meta["s"], t=meta["t"])
            for name, meta in footer["keys"].items()]


def block_points(header):
    """How many positions a block takes: one per point."""
    return sum(e["n"] for e in header["keys"])


def may_be_rewound(fold, header):
    """Whether a rewind *fold* knows could hide points of this block."""
    rewinds = fold.get("rewinds")
    if not rewinds:
        return False
    markers = [(r[0], iso_to_us(r[1])) for r in rewinds]
    return any(
        r_step < entry["s"][1] and (r_ts is None or entry["t"][0] <= r_ts)
        for entry in header["keys"] if entry.get("has_step")
        for r_step, r_ts in markers
    )


def apply_header(fold, writer, base, header):
    """Fold one block header (or footer, see :func:`footer_entries`)."""
    for entry in header["keys"]:
        _apply_key(fold, base_key(entry["k"]), entry, writer, base)
    return fold


def apply_block_points(fold, writer, base, block):
    """Fold a decoded block point by point (rewinds applied)."""
    points = sorted(((ts, step, base_key(name), value)
                     for name, cols in block.keys.items()
                     for ts, step, value in _points(cols)), key=lambda p: p[0])
    for offset, entry in enumerate(points_to_entries(points)):
        _apply(fold, entry, (entry["timestamp"], writer, base + offset))
    return fold


def _points(cols):
    for i in range(len(cols)):
        yield cols.ts[i], cols.steps[i] if cols.has_step else None, cols.values[i]


def _apply_key(fold, name, entry, writer, base):
    n = entry["n"]
    first_value, _, first_ts = entry["first"]
    last_value, _, last_ts = entry["last"]
    first_key = (us_to_iso(first_ts), writer, base)
    last_key = (us_to_iso(last_ts), writer, base + n - 1)
    if n == 1:
        track_extrema(fold, name, first_value, first_key)
    else:
        track_block(fold, name, first_value, first_key, entry["sum"])
    _keep_latest(fold["metrics"], name, last_value, last_key)
    if fold["last_metric"] is None or last_key >= tuple(fold["last_metric"][1]):
        fold["last_metric"] = (last_key[0], last_key)
