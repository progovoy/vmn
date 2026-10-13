#!/usr/bin/env python3
"""How many distinct values each param has, as the board's Group by menu
needs it: exact up to :data:`DISTINCT_CAP`, then only "more than that"."""
import math

# The menu offers a param only with at most this many values (plan 22 G2).
DISTINCT_CAP = 20
# Values tracked per key before it counts as "many" for good: past it a
# leaving row cannot bring the key back under the cap, and memory stays bounded.
_TRACKED = 64


def value_key(value):
    """A hashable stand-in for a verbatim param value (lists, dicts too);
    every NaN is one value (NaN != NaN, and each row parses its own)."""
    if isinstance(value, float) and math.isnan(value):
        return ("float", "nan")
    try:
        hash(value)
    except TypeError:
        return ("repr", repr(value))
    return (type(value).__name__, value)


def distinct_count(values):
    """What the payload says for *values*' distinct count."""
    return min(len(values), DISTINCT_CAP + 1)


class ParamValues:
    """``{param key: {value key: rows}}``; a key past :data:`_TRACKED`
    values maps to None. Copies share the per-key counters until one moves."""

    def __init__(self, counts=None):
        self._counts = counts or {}
        self._own = set()

    def copy(self):
        return ParamValues(dict(self._counts))

    def move(self, params, by):
        for key, value in params.items():
            values = self._writable(key)
            if values is None:
                continue
            vkey = value_key(value)
            count = values.get(vkey, 0) + by
            if count > 0:
                values[vkey] = count
            else:
                values.pop(vkey, None)
            if len(values) > _TRACKED:
                self._counts[key] = None
            elif not values:
                del self._counts[key]
                self._own.discard(key)

    def _writable(self, key):
        if key not in self._counts:
            self._counts[key] = {}
            self._own.add(key)
        elif key not in self._own and self._counts[key] is not None:
            self._counts[key] = dict(self._counts[key])
            self._own.add(key)
        return self._counts[key]

    def payload(self, keys):
        """Counts of the *keys* still carried by some row."""
        return {key: DISTINCT_CAP + 1 if values is None else distinct_count(values)
                for key, values in sorted(self._counts.items()) if key in keys}
