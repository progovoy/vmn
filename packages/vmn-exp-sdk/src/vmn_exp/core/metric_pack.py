#!/usr/bin/env python3
"""A run's ``metric_summary`` as the index keeps it: packed.

``{metric: {"last", "min", "max", "first", "mean"}}`` costs a dict and five
float objects per metric — about 450 bytes, for every metric a run logs more
than once, for every run the index holds. :class:`PackedSummary` keeps the
names (one tuple shared by the runs logging the same metrics) and the values
in one ``array("d")``: about 40 bytes a metric.

Every value reads back exactly as it was given: an ``int`` stays an int (a
bit per value says so), ``min``/``max``/``mean`` — finite or None (see
:mod:`vmn_exp.core.metric_summary`) — keep None as NaN, and anything else no
float holds as is (a NaN min, a bool, an int beyond 2**53) is kept aside.
It reads like the dict it packs (``items``, ``get``, ``in``, ``len``), each
metric's summary a fresh dict.
"""
import math
from array import array

from vmn_exp.core.index_intern import STRINGS

FIELDS = ("last", "min", "max", "first", "mean")
_WIDTH = len(FIELDS)
_NONE_AS_NAN = frozenset(FIELDS.index(f) for f in ("min", "max", "mean"))
_EXACT_INT = 2 ** 53
_ODD = object()


def _packed(value, field):
    """*value* as the float that stands for it in *field*, or :data:`_ODD`."""
    kind = type(value)
    if kind is float:
        return _ODD if field in _NONE_AS_NAN and math.isnan(value) else value
    if kind is int and -_EXACT_INT <= value <= _EXACT_INT:
        return float(value)
    if value is None and field in _NONE_AS_NAN:
        return math.nan
    return _ODD


class PackedSummary:
    __slots__ = ("names", "values", "ints", "odd")

    def __init__(self, names, values, ints=0, odd=None):
        self.names, self.values, self.ints, self.odd = names, values, ints, odd

    @classmethod
    def of(cls, summary):
        """*summary* packed (itself if it is); None when it is empty."""
        if not summary or isinstance(summary, cls):
            return summary or None
        names = STRINGS(tuple(STRINGS(name) for name in summary))
        values, ints, odd = array("d"), 0, None
        for seen in summary.values():
            for field, key in enumerate(FIELDS):
                value = seen[key]
                packed = _packed(value, field)
                if packed is _ODD:
                    odd = odd or {}
                    odd[len(values)] = value
                    packed = 0.0
                elif type(value) is int:
                    ints |= 1 << len(values)
                values.append(packed)
        return cls(names, values, ints, odd)

    def _value(self, at):
        if self.odd and at in self.odd:
            return self.odd[at]
        value = self.values[at]
        if self.ints >> at & 1:
            return int(value)
        if at % _WIDTH in _NONE_AS_NAN and math.isnan(value):
            return None
        return value

    def _seen(self, i):
        start = i * _WIDTH
        return {key: self._value(start + n) for n, key in enumerate(FIELDS)}

    def items(self):
        return ((name, self._seen(i)) for i, name in enumerate(self.names))

    def get(self, name, default=None):
        try:
            return self._seen(self.names.index(name))
        except ValueError:
            return default

    def to_dict(self):
        """The summary as ``{metric: {"last", "min", "max", "first", "mean"}}``."""
        return dict(self.items())

    def __contains__(self, name):
        return name in self.names

    def __iter__(self):
        return iter(self.names)

    def __len__(self):
        return len(self.names)

    def __eq__(self, other):
        if not isinstance(other, PackedSummary):
            return NotImplemented
        return repr(self) == repr(other)

    __hash__ = None

    def __repr__(self):
        return f"PackedSummary({self.to_dict()!r})"

    def __getstate__(self):
        return (self.names, self.values, self.ints, self.odd)

    def __setstate__(self, state):
        self.names, self.values, self.ints, self.odd = state
