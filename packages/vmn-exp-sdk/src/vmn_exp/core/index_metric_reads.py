#!/usr/bin/env python3
"""Range reads of a record's metric objects for the index's fold.

A listing can name an object its writer has since replaced: the owner rolls
a live stream's segments into a wider ``.vmx`` and deletes the ones it
covers, the ``.vmx`` before included. Reading such a name answers None (S3
``NoSuchKey``); :func:`object_read` raises :class:`MetricObjectGone` instead,
so the fold is redone from a fresh listing rather than from a None.
"""


class MetricObjectGone(Exception):
    """A metric object the record's listing named was gone when read."""


def object_read(storage, where, name):
    """``read(offset, length)`` of metric object *name* of record *where*."""
    def read(offset, length):
        data = storage.read_range(*where, name, offset, length)
        if data is None:
            raise MetricObjectGone(name)
        return data

    return read
