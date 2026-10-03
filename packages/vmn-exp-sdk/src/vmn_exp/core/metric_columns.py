#!/usr/bin/env python3
"""Columns of one metric key and the stdlib packing both metric codecs share.

Steps and timestamps are int64 (timestamps in microseconds), values float64
(plan 12 D5). Integer columns are stored delta-encoded, first value absolute,
so a slowly growing step or clock compresses to a byte or two per point.
Everything is little-endian on disk whatever the host is.
"""
import math
import sys
from array import array
from dataclasses import dataclass
from itertools import accumulate
from typing import Optional, Sequence

_SWAP = sys.byteorder != "little"


@dataclass
class Columns:
    """One key's points: ``steps`` is ``None`` for a step-less key."""

    steps: Optional[Sequence[int]]
    ts: Sequence[int]
    values: Sequence[float]

    @property
    def has_step(self):
        return self.steps is not None

    def __len__(self):
        return len(self.ts)


def _to_bytes(arr):
    if _SWAP:
        arr.byteswap()
    return arr.tobytes()


def _from_bytes(typecode, data):
    arr = array(typecode)
    arr.frombytes(data)
    if _SWAP:
        arr.byteswap()
    return arr


def pack_deltas(ints):
    """*ints* as delta-encoded little-endian int64 bytes."""
    ints = list(ints)
    deltas = [b - a for a, b in zip(ints, ints[1:])]
    return _to_bytes(array("q", ints[:1] + deltas))


def unpack_deltas(data):
    return array("q", accumulate(_from_bytes("q", data)))


def pack_floats(values):
    return _to_bytes(array("d", values))


def unpack_floats(data):
    return _from_bytes("d", data)


def point(cols, i):
    """``[value, step, ts]`` of the *i*-th point (step ``None`` if step-less)."""
    step = cols.steps[i] if cols.steps is not None else None
    return [cols.values[i], step, cols.ts[i]]


def add_exact(partials, value):
    """Shewchuk's non-overlapping *partials* (the ``math.fsum`` recipe) with
    *value* added: their exact sum, so a mean does not depend on the order
    values are added in. A handful of floats at most in practice."""
    out = []
    for other in partials:
        if abs(value) < abs(other):
            value, other = other, value
        high = value + other
        low = other - (high - value)
        if low:
            out.append(low)
        value = high
    out.append(value)
    return tuple(out)


def exact_parts(values):
    """The partials of the exact sum of *values* (see :func:`add_exact`)."""
    parts = ()
    for value in values:
        parts = add_exact(parts, value)
    return list(parts)


def finite_summary(cols):
    """``{n, sum, parts, min, max}`` over the finite values (*parts*: the
    exact sum's partials, so folds of blocks add up exactly); min/max are the first
    of equals as ``[value, step, ts]`` (``None`` without finite values)."""
    lo = hi = None
    finite = []
    for i, value in enumerate(cols.values):
        if not math.isfinite(value):
            continue
        finite.append(value)
        if lo is None or value < cols.values[lo]:
            lo = i
        if hi is None or value > cols.values[hi]:
            hi = i
    return {
        "n": len(finite),
        "sum": math.fsum(finite),
        "parts": exact_parts(finite),
        "min": None if lo is None else point(cols, lo),
        "max": None if hi is None else point(cols, hi),
    }


def key_summary(name, cols):
    """The per-key header of a block (plan 12 §3.1)."""
    last = len(cols) - 1
    return {
        "k": name,
        "n": len(cols),
        "has_step": cols.has_step,
        "s": [cols.steps[0], cols.steps[last]] if cols.has_step else None,
        "t": [cols.ts[0], cols.ts[last]],
        "sum": finite_summary(cols),
        "first": point(cols, 0),
        "last": point(cols, last),
    }
