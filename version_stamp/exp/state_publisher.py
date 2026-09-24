#!/usr/bin/env python3
"""Publish a run's ``run_state.yml`` without letting a slow remote stall liveness.

The heartbeat is only as good as its cadence: a beat that waits behind a hung
S3 PUT is a beat that did not happen, and the run reads ``stuck`` while it
trains. So the local copy is written inline (it is what local readers see, and
it is cheap), and the remote copy goes to a :class:`Coalescing` worker — only
the newest pending state is uploaded, in order, so the final state can never be
overwritten by an older heartbeat that was still in flight.
"""
import functools

import yaml

from version_stamp.cli.snapshot import CachedSnapshotStorage
from version_stamp.core.experiment_status import RUN_STATE_FILE
from version_stamp.exp.background import Coalescing


def split_storage(storage):
    """``(inline, background)`` halves of *storage* for run-state writes.

    A local-first cache with a remote is split into its two sides; a store that
    is remote only is written entirely in the background; anything else (a
    local store, or a caller's own wrapper) is written inline, as given.
    """
    if isinstance(storage, CachedSnapshotStorage):
        # Private, but the cache's documented shape (local-first + optional
        # remote), and it exposes no public accessor for its two sides.
        return storage._local, storage._remote
    if getattr(storage, "is_remote", lambda: False)():
        return None, storage
    return storage, None


class RunStatePublisher:
    """Writes one run's state: inline locally, latest-wins in order remotely."""

    def __init__(self, storage, app_name, verstr):
        self._storage = storage
        self._inline, remote = split_storage(storage)
        self._split = self._inline is not storage
        self._where = (app_name, verstr, RUN_STATE_FILE)
        self._remote = None
        if remote is not None:
            upload = functools.partial(remote.save_file, *self._where)
            self._remote = Coalescing(upload, "vmn-run-state")

    def publish(self, state):
        """Write *state* now locally; queue it for the remote. Raises on a
        failed local write, like the storage call it replaces."""
        data = yaml.dump(state, sort_keys=False)
        if self._inline is not None:
            refused = self._inline.save_file(*self._where, data) is False
            if refused and self._split:
                # The record exists only remotely so far (a run resumed on
                # another host): the full store fetches it, then writes both.
                self._storage.save_file(*self._where, data)
                return
        if self._remote is not None:
            self._remote.submit(data)

    def close(self, timeout):
        """Upload what is pending, then stop. False if that did not finish."""
        return self._remote.close(timeout) if self._remote is not None else True
