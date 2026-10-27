#!/usr/bin/env python3
"""A read-only mapping that successive generations share (plan 26 F00).

An index snapshot keys several maps by verstr (run states, parent edges,
rows, side tables). Copying each in full per generation cost ~10 ms and
~21 MB per 486k-entry map, at about a generation a second, while only a few
dozen entries changed. A :class:`SharedMap` is a frozen *base* dict plus an
*overlay* of the keys changed or removed since: :meth:`SharedMap.derive`
makes the next generation from the changes alone, and no generation ever
sees a later one's.

The overlay is a short stack of frozen levels, newest last, merged like a
binary counter (a level is merged into the one below once it is at least
half its size), so a derive copies O(changes x log(overlay)) entries and a
lookup checks a few small dicts before the base. Once the overlay passes
:data:`FOLD_FRACTION` of the base it is folded into a new base, O(1)
amortized per change.

Iteration follows the base's order, then the keys the overlay added (in the
order they were first added); a fold keeps that order.
"""
from collections.abc import ItemsView, Mapping, ValuesView

# The overlay's share of the base past which it folds into a new base. At
# 50 random changes a generation to a 50k map, 0.1 keeps ~1.2% of the bytes
# a dict copy per generation would (0.05: ~2.2%); a live server's changes
# repeat its live runs' keys, which keep the overlay small (~0.2%).
FOLD_FRACTION = 0.1
# The overlay size never worth a fold (a small or empty base).
_MIN_FOLD = 64
_GONE = object()  # an overlay entry hiding the key below it
_ABSENT = object()


class SharedMap(Mapping):
    """*base* (never changed afterwards: share it, don't mutate it) with
    *overlay*'s entries set and *removed*'s keys taken out."""

    __slots__ = ("_base", "_levels", "_len")

    def __init__(self, base=None, overlay=None, removed=()):
        base = {} if base is None else base
        self._base, self._levels, self._len = base, (), len(base)
        if overlay or removed:
            derived = self.derive(overlay, removed)
            self._base, self._levels, self._len = derived._base, derived._levels, derived._len

    @classmethod
    def _of(cls, base, levels, length):
        new = cls.__new__(cls)
        new._base, new._levels, new._len = base, levels, length
        return new

    def derive(self, changes=None, removed=()):
        """The next generation: *changes* ``{key: value}`` set, *removed*
        keys taken out (a key in both is removed)."""
        gone = set(removed)
        level, length = {}, self._len
        for key, value in (changes or {}).items():
            if key not in gone:
                length += key not in self
                level[key] = value
        for key in gone:
            if key in self:
                level[key] = _GONE
                length -= 1
        if not level:
            return self
        if not self._base and not self._levels:  # nothing to hide: no tombstones
            return SharedMap._of(level, (), length)
        levels = _merged(self._levels + (level,), self._base)
        if sum(map(len, levels)) > max(FOLD_FRACTION * len(self._base), _MIN_FOLD):
            folded = SharedMap._of(self._base, levels, length)
            return SharedMap._of(dict(folded.items()), (), length)
        return SharedMap._of(self._base, levels, length)

    @property
    def overlay_len(self):
        """Entries in the overlay (a key changed twice may count twice)."""
        return sum(map(len, self._levels))

    def __getitem__(self, key):
        for level in reversed(self._levels):
            value = level.get(key, _ABSENT)
            if value is not _ABSENT:
                if value is _GONE:
                    raise KeyError(key)
                return value
        return self._base[key]

    def get(self, key, default=None):
        for level in reversed(self._levels):
            value = level.get(key, _ABSENT)
            if value is not _ABSENT:
                return default if value is _GONE else value
        return self._base.get(key, default)

    def __contains__(self, key):
        return self.get(key, _ABSENT) is not _ABSENT

    def __len__(self):
        return self._len

    def __iter__(self):
        if not self._levels:
            return iter(self._base)
        return (key for key, _ in self._pairs())

    def items(self):
        return _Items(self)

    def values(self):
        return _Values(self)

    def _pairs(self):
        base = self._base
        if not self._levels:
            yield from base.items()
            return
        overlay = {}
        for level in self._levels:
            overlay.update(level)
        for key, value in base.items():
            newer = overlay.get(key, _ABSENT)
            if newer is _ABSENT:
                yield key, value
            elif newer is not _GONE:
                yield key, newer
        for key, value in overlay.items():
            if value is not _GONE and key not in base:
                yield key, value

    def __repr__(self):
        return f"SharedMap(<{self._len} entries, overlay {self.overlay_len}>)"


class _Items(ItemsView):
    __slots__ = ()

    def __iter__(self):
        return self._mapping._pairs()


class _Values(ValuesView):
    __slots__ = ()

    def __iter__(self):
        return (value for _, value in self._mapping._pairs())


def _merged(levels, base):
    """*levels* with the newest merged down while it is at least half the
    size of the one below; the bottom level drops what hides no base key."""
    levels = list(levels)
    while len(levels) > 1 and 2 * len(levels[-1]) >= len(levels[-2]):
        newer = levels.pop()
        merged = dict(levels[-1])
        merged.update(newer)
        if len(levels) == 1:
            merged = {k: v for k, v in merged.items() if v is not _GONE or k in base}
        levels[-1] = merged
    return tuple(levels)
