#!/usr/bin/env python3
"""Client-side histograms: ``{"bins": [edges], "counts": [...]}`` of the finite values.

numpy computes them when installed; the pure-Python path gives the same bins
(``len(bins) == len(counts) + 1``, equal widths, the last bin closed on the
right, a constant widened to ``value +- 0.5``). A ready
``{"bins": edges, "counts": counts}`` mapping is checked by :func:`precomputed`.
"""
import math


def _numpy():
    try:
        import numpy
    except ImportError:
        return None
    return numpy


def positive_int(value, what):
    """*value*, refused unless a positive int (bools are not ints here)."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{what} must be a positive integer, got {value!r}")
    return value


def value_range(lo, hi):
    """The binned range of finite values *lo*..*hi*: a constant widened to +-0.5."""
    return (lo - 0.5, hi + 0.5) if lo == hi else (lo, hi)


def equal_edges(lo, hi, bins):
    """*bins* + 1 equal-width edges over [*lo*, *hi*], the last exactly *hi*."""
    width = (hi - lo) / bins
    return [lo + i * width for i in range(bins)] + [hi]


def _as_array_like(values):
    """Tensors and the like to something iterable (numpy when possible)."""
    if hasattr(values, "detach"):  # torch
        values = values.detach().cpu().numpy()
    return values


def _with_numpy(np, values, bins):
    arr = np.asarray(values, dtype=np.float64).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    lo, hi = value_range(float(arr.min()), float(arr.max()))
    counts, edges = np.histogram(arr, bins=bins, range=(lo, hi))
    return {"bins": [float(e) for e in edges], "counts": [int(c) for c in counts]}


def _flat(values):
    for v in values:
        if isinstance(v, (list, tuple)):
            yield from _flat(v)
        else:
            yield v


def _pure(values, bins):
    finite = [float(v) for v in _flat(values) if math.isfinite(float(v))]
    if not finite:
        return None
    lo, hi = value_range(min(finite), max(finite))
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in finite:
        counts[min(int((v - lo) / width), bins - 1)] += 1
    return {"bins": equal_edges(lo, hi, bins), "counts": counts}


def precomputed(binned):
    """A caller's own ``{"bins", "counts"}``, checked: one more edge than counts."""
    edges, counts = binned.get("bins"), binned.get("counts")
    if not counts or edges is None or len(edges) != len(counts) + 1:
        raise ValueError("a precomputed histogram needs len(bins) == len(counts) + 1")
    return {"bins": [float(e) for e in edges], "counts": [int(c) for c in counts]}


def histogram(values, bins=64):
    """The histogram of *values*' finite entries, or None when there are none."""
    positive_int(bins, "bins")
    values = _as_array_like(values)
    np = _numpy()
    return _with_numpy(np, values, bins) if np is not None else _pure(values, bins)
