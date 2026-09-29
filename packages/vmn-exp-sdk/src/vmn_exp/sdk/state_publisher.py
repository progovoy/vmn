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

from vmn_exp.core.background import Coalescing
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.cached import CachedSnapshotStorage


def split_storage(storage, app_name, verstr):
    """``(inline, background upload or None)`` of *storage* for one run's
    state writes; the upload takes the state's serialized ``data``.

    A local-first cache with a remote is split into its local side and an
    upload to the remote — made only once the remote is known to hold this
    run (:meth:`CachedSnapshotStorage.remote_for`, whose check may be a GET,
    so it runs in the background too). A store that is remote only is written
    entirely in the background; anything else (a local store, or a caller's
    own wrapper) is written inline, as given.
    """
    if isinstance(storage, CachedSnapshotStorage):
        # Private, but the cache's documented shape (local-first + optional
        # remote), and it exposes no public accessor for its local side.
        if storage._remote is None:
            return storage._local, None
        return storage._local, functools.partial(
            _upload_if_held, storage, app_name, verstr
        )
    if getattr(storage, "is_remote", lambda: False)():
        return None, functools.partial(
            storage.save_file, app_name, verstr, RUN_STATE_FILE
        )
    return storage, None


def _upload_if_held(storage, app_name, verstr, data):
    remote = storage.remote_for(app_name, verstr)
    if remote is not None:
        remote.save_file(app_name, verstr, RUN_STATE_FILE, data)


class RunStatePublisher:
    """Writes one run's state: inline locally, latest-wins in order remotely."""

    def __init__(self, storage, app_name, verstr):
        self._storage = storage
        self._inline, upload = split_storage(storage, app_name, verstr)
        self._split = self._inline is not storage
        self._where = (app_name, verstr, RUN_STATE_FILE)
        self._remote = None
        if upload is not None:
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
