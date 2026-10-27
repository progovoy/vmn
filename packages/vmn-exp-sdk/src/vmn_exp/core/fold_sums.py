#!/usr/bin/env python3
"""What a writer's folded metric points add up to, kept per stream key, so a
refold of the record (its log rolled up or compacted) folds them again
without reading a segment (plan 12 §5.3).

A writer's *sums* are ``{stream key: entry}``: a block header's key entry
over every point the writer's folded blocks hold — ``n``, ``first``/``last``,
the finite ``sum`` summary, ``s``/``t`` as the step and timestamp bounds (so
:func:`~vmn_exp.core.fold_blocks.may_be_rewound` stays conservative) — and
``p``, the positions of its first and last points. Folding them
(:func:`~vmn_exp.core.fold_blocks.apply_sums`) gives what the blocks gave, as
a block's header gives what its points do. Pure: no I/O.
"""
from vmn_exp.core.metric_columns import exact_parts
from vmn_exp.core.metric_time import us_to_iso


def add_block(sums, base, header):
    """Widen *sums* by one block's *header* (or footer entries) folded at *base*."""
    for entry in header["keys"]:
        mine = _entry(entry, base)
        held = sums.get(entry["k"])
        sums[entry["k"]] = mine if held is None else _combined(held, mine)
    return sums


def counts(sums):
    """``{stream key: points}`` the *sums* hold."""
    return {name: entry["n"] for name, entry in sums.items()}


def _entry(entry, base):
    s = entry.get("s")
    return {
        "n": entry["n"], "first": entry["first"], "last": entry["last"], "sum": entry["sum"],
        "has_step": entry.get("has_step"), "s": sorted(s) if s else None,
        "t": sorted(entry["t"]), "p": [base, base + entry["n"] - 1],
    }


def _key(point, at):
    return us_to_iso(point[2]), at


def _combined(held, new):
    first = held if _key(held["first"], held["p"][0]) <= _key(new["first"], new["p"][0]) else new
    last = new if _key(new["last"], new["p"][1]) >= _key(held["last"], held["p"][1]) else held
    return {
        "n": held["n"] + new["n"], "first": first["first"], "last": last["last"],
        "sum": _finite(held["sum"], new["sum"]), "has_step": held["has_step"],
        "s": _bounds(held["s"], new["s"]), "t": _bounds(held["t"], new["t"]),
        "p": [first["p"][0], last["p"][1]],
    }


def _bounds(a, b):
    if a is None or b is None:
        return a or b
    return [min(a[0], b[0]), max(a[1], b[1])]


def _finite(a, b):
    """Two ``{n, sum, parts, min, max}`` finite summaries as one, exactly."""
    if not b.get("n"):
        return a
    if not a.get("n"):
        return b
    parts = exact_parts([*(a.get("parts") or [a["sum"]]), *(b.get("parts") or [b["sum"]])])
    return {
        "n": a["n"] + b["n"], "sum": a["sum"] + b["sum"], "parts": parts,
        "min": a["min"] if a["min"][0] <= b["min"][0] else b["min"],
        "max": a["max"] if a["max"][0] >= b["max"][0] else b["max"],
    }
