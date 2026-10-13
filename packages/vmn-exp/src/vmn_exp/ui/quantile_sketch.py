#!/usr/bin/env python3
"""A small mergeable, removable quantile sketch (DDSketch-style).

Values fall into logarithmic buckets ``(γ^(k-1), γ^k]`` per sign, so any
quantile is within :data:`RELATIVE_ACCURACY` of the value at its exact rank.
Buckets hold counts, so a value is removed by adding it with ``by=-1`` and
two sketches merge by adding counts: a job's rollup subtracts the runs that
left and adds the ones that joined without seeing the rest. Each sign keeps
at most :attr:`QuantileSketch.MAX_BINS` buckets (≤ 2 KB as packed counts);
past that the smallest magnitudes collapse into one floor bucket, which
only ever rises, so a removal lands where its value was counted.
"""
import heapq
import math

from vmn_exp.core.values import is_finite_number

RELATIVE_ACCURACY = 0.01
_GAMMA = (1 + RELATIVE_ACCURACY) / (1 - RELATIVE_ACCURACY)
_LOG_GAMMA = math.log(_GAMMA)
# Magnitudes below this count as zero.
MIN_MAGNITUDE = 1e-12


def _key(magnitude):
    return math.ceil(math.log(magnitude) / _LOG_GAMMA)


def _value(key):
    return 2 * _GAMMA ** key / (_GAMMA + 1)


class _Side:
    """One sign's ``{bucket: count}`` and its collapse floor."""

    __slots__ = ("bins", "floor")

    def __init__(self, bins=None, floor=None):
        self.bins = bins or {}
        self.floor = floor

    def copy(self):
        return _Side(dict(self.bins), self.floor)

    def add(self, key, by):
        if self.floor is not None and key < self.floor:
            key = self.floor
        count = self.bins.get(key, 0) + by
        if count:
            self.bins[key] = count
        else:
            self.bins.pop(key, None)

    def raise_floor(self, floor):
        if floor is None or (self.floor is not None and floor <= self.floor):
            return
        self.floor = floor
        low = [k for k in self.bins if k < floor]
        if low:
            self.bins[floor] = self.bins.get(floor, 0) + sum(self.bins.pop(k) for k in low)

    def bound(self, limit):
        if len(self.bins) > limit:
            self.raise_floor(heapq.nsmallest(len(self.bins) - limit + 1, self.bins)[-1])

    def __eq__(self, other):
        return self.bins == other.bins and self.floor == other.floor


class QuantileSketch:
    """Counts of finite values in relative-accuracy buckets; NaN, inf and
    non-numbers are ignored."""

    MAX_BINS = 512
    __slots__ = ("_neg", "_pos", "_zero", "count")

    def __init__(self):
        self._pos, self._neg = _Side(), _Side()
        self._zero = 0
        self.count = 0

    def copy(self):
        out = QuantileSketch()
        out._pos, out._neg = self._pos.copy(), self._neg.copy()
        out._zero, out.count = self._zero, self.count
        return out

    def add(self, value, by=1):
        if not is_finite_number(value):
            return
        self.count += by
        magnitude = abs(value)
        if magnitude < MIN_MAGNITUDE:
            self._zero += by
            return
        side = self._pos if value > 0 else self._neg
        side.add(_key(magnitude), by)
        side.bound(self.MAX_BINS)

    def merge(self, other, by=1):
        """Adds *other*'s counts (``by=-1``: takes them away)."""
        for mine, theirs in ((self._pos, other._pos), (self._neg, other._neg)):
            mine.raise_floor(theirs.floor)
            for key, count in theirs.bins.items():
                mine.add(key, by * count)
            mine.bound(self.MAX_BINS)
        self._zero += by * other._zero
        self.count += by * other.count

    def bins(self):
        """Logarithmic buckets held (the zero count is not one)."""
        return len(self._pos.bins) + len(self._neg.bins)

    def _items(self):
        """``(representative value, count)`` from the lowest value up."""
        for key in sorted(self._neg.bins, reverse=True):
            yield -_value(key), self._neg.bins[key]
        if self._zero:
            yield 0.0, self._zero
        for key in sorted(self._pos.bins):
            yield _value(key), self._pos.bins[key]

    def quantile(self, q):
        """The value at rank ``round(q * (count - 1))``, or None when empty."""
        return self.quantiles([q])[0]

    def quantiles(self, qs):
        """:meth:`quantile` of each of *qs*, in one pass over the buckets."""
        if self.count <= 0:
            return [None] * len(qs)
        ranks = sorted((round(min(max(q, 0.0), 1.0) * (self.count - 1)), i)
                       for i, q in enumerate(qs))
        out, seen, at = [None] * len(qs), 0, 0
        for value, count in self._items():
            seen += count
            while at < len(ranks) and seen > ranks[at][0]:
                out[ranks[at][1]] = value
                at += 1
            if at == len(ranks):
                break
        return out

    def histogram(self, bins=20, lo=None, hi=None):
        """``[{lo, hi, count}]`` of *bins* equal-width bins over [*lo*, *hi*]
        (default: the sketch's own range); one bin when the range is a point."""
        if self.count <= 0:
            return []
        lo = self.quantile(0.0) if lo is None else lo
        hi = self.quantile(1.0) if hi is None else hi
        if hi <= lo:
            return [{"lo": lo, "hi": hi, "count": self.count}]
        edges = [lo + (hi - lo) * i / bins for i in range(bins)] + [hi]
        counts = [0] * bins
        for value, count in self._items():
            at = int((value - lo) / (hi - lo) * bins)
            counts[min(max(at, 0), bins - 1)] += count
        return [{"lo": edges[i], "hi": edges[i + 1], "count": counts[i]} for i in range(bins)]

    def __eq__(self, other):
        return (isinstance(other, QuantileSketch) and self.count == other.count
                and self._zero == other._zero and self._pos == other._pos
                and self._neg == other._neg)
