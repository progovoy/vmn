#!/usr/bin/env python3
"""Which workspace app an index snapshot belongs to: what the board's
warm-up and job rollups resolve the app's conf and store settings by (plan
28 A0), given a snapshot alone. Snapshots served to a request and those a
refresh published are noted; a schema view is found by its snapshot too.
Held weakly: a superseded generation is not kept alive.
"""
import threading
import weakref

from vmn_exp.core.index_snapshot import schema_less


class SnapshotOwners:
    def __init__(self):
        self._of_snapshot = weakref.WeakKeyDictionary()
        self._of_index = weakref.WeakKeyDictionary()
        self._lock = threading.Lock()

    def serves(self, index, owner):
        """*index* serves *owner* (``(workspace, app name)``)."""
        self._put(self._of_index, index, owner)

    def refreshed(self, index, snapshot):
        """A refresh listener: *index* published *snapshot*."""
        owner = self._get(self._of_index, index)
        if owner is not None:
            self.note(snapshot, owner)

    def note(self, snapshot, owner):
        """*snapshot* (or a schema view of it) belongs to *owner*."""
        self._put(self._of_snapshot, snapshot, owner)

    def of(self, snapshot):
        """*snapshot*'s owner, else None."""
        owner = self._get(self._of_snapshot, snapshot)
        if owner is None:
            owner = self._get(self._of_snapshot, schema_less(snapshot))
            if owner is not None:
                self.note(snapshot, owner)
        return owner

    def _get(self, table, key):
        try:
            with self._lock:
                return table.get(key)
        except TypeError:  # not weakly referable (a test double)
            return None

    def _put(self, table, key, owner):
        try:
            with self._lock:
                table[key] = owner
        except TypeError:
            pass
