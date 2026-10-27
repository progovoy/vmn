#!/usr/bin/env python3
"""Reads of the objects one listing named, which a compaction may have merged
and deleted since (the owner's live rollup, store upkeep).

The first object found missing makes the listing stale: :class:`ListedReads`
raises :class:`StaleListing` for it and for every read after it, without a
request, and :func:`read_each` reads a long list's first object alone first —
so a stale listing costs one miss (a few at most), not a 404 per segment, and
the reader lists the record once more (``core/index_logs.py`` does the same
for the experiment index).
"""
from concurrent.futures import ThreadPoolExecutor

from vmn_exp.storage.thread_context import in_caller_context

# Reads past which the first is made alone first: a live run's few new
# segments cost no extra round trip.
PROBE_OVER = 4
READ_WORKERS = 16


class StaleListing(Exception):
    """A listed object is gone: list the record again."""


class ListedReads:
    """*storage*'s ``read_range``/``read_file_from`` of listed objects."""

    def __init__(self, storage):
        self._storage = storage
        self.stale = False

    def is_remote(self):
        return self._storage.is_remote()

    def read_range(self, app_name, verstr, name, offset, length):
        return self._checked(self._storage.read_range, app_name, verstr, name, offset, length)

    def read_file_from(self, app_name, verstr, name, offset):
        return self._checked(self._storage.read_file_from, app_name, verstr, name, offset)

    def _checked(self, read, *args):
        if not self.stale:
            data = read(*args)
            if data is not None:
                return data
            self.stale = True
        raise StaleListing()


def read_each(read, items, thread_name):
    """``[read(item)]`` in order, concurrently; of more than
    :data:`PROBE_OVER` items the first is read before the others."""
    items = list(items)
    if len(items) > PROBE_OVER:
        first = read(items[0])
        return [first] + _concurrently(read, items[1:], thread_name)
    return _concurrently(read, items, thread_name)


def _concurrently(read, items, thread_name):
    if len(items) < 2:
        return [read(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(READ_WORKERS, len(items)),
                            thread_name_prefix=thread_name) as pool:
        return list(pool.map(in_caller_context(read), items))
