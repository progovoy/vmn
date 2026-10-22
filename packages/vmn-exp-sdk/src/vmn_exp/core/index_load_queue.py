#!/usr/bin/env python3
"""The order a remote cold load reads its records in.

Newest first, a chunk at a time — but an outer run is created before its
inner runs, so newest first alone would read it last and leave the Outer runs
board empty until the whole index had loaded. A loaded record's parent not
yet read is therefore read next (:meth:`LoadQueue.want`), ahead of the rest,
which pulls in the whole ancestor chain one small chunk per generation.
Work put off for :meth:`LoadQueue.later` comes after all the rest.
"""
from itertools import islice


class LoadQueue:
    def __init__(self, work, size):
        self._pending = {item[0]: item for item in work}  # in load order
        self._wanted = {}
        self._later = []
        self._size = size

    def __bool__(self):
        return bool(self._pending or self._later)

    def take(self):
        """The next chunk: wanted records first, else the next *size*, else
        what was put off."""
        keys = list(islice(self._wanted, self._size)) or list(islice(self._pending, self._size))
        for key in keys:
            self._wanted.pop(key, None)
        if keys:
            return [self._pending.pop(key) for key in keys]
        chunk, self._later = self._later[:self._size], self._later[self._size:]
        return chunk

    def later(self, items):
        """Queue *items* after everything else."""
        self._later.extend(items)

    def want(self, keys):
        """Read the pending ones of *keys* in the next chunk."""
        for key in keys:
            if key in self._pending:
                self._wanted[key] = None
