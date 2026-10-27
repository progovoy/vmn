#!/usr/bin/env python3
"""Reads of the objects one listing named, which a compaction may have merged
and deleted since (the owner's live rollup, store upkeep).

The first object found missing makes the listing stale: :class:`ListedReads`
raises :class:`StaleListing` for it and for every read after it, without a
request, and :func:`read_each` reads a long list's first object alone first —
so a stale listing costs one miss (a few at most), not a 404 per segment, and
the reader lists the record once more, as the experiment index does
(:mod:`vmn_exp.core.index_logs`).
"""
from vmn_exp.core.index_logs import PROBE_OVER
from vmn_exp.storage.s3_base import parallel_map


class StaleListing(Exception):
    """A listed object is gone: list the record again."""


class ListedReads:
    """*storage*'s ``read_range``/``read_file_from`` of listed objects."""

    def __init__(self, storage):
        self._storage = storage
        self._stale = False

    def is_remote(self):
        return self._storage.is_remote()

    def read_range(self, app_name, verstr, name, offset, length):
        return self._checked(self._storage.read_range, app_name, verstr, name, offset, length)

    def read_file_from(self, app_name, verstr, name, offset):
        return self._checked(self._storage.read_file_from, app_name, verstr, name, offset)

    def _checked(self, read, *args):
        if not self._stale:
            data = read(*args)
            if data is not None:
                return data
            self._stale = True
        raise StaleListing()


def read_each(read, items):
    """``[read(item)]`` in order, concurrently; of more than
    :data:`PROBE_OVER` items the first is read before the others."""
    items = list(items)
    if len(items) > PROBE_OVER:
        first = read(items[0])
        return [first] + parallel_map(read, items[1:])
    return parallel_map(read, items)


def store_identity(storage):
    """What tells *storage*'s records from another store's in a cache key."""
    identity_of = getattr(storage, "cache_identity", None)
    return (identity_of() if identity_of else None) or id(storage)
