#!/usr/bin/env python3
"""Publish a run's ``run_state.yml`` without letting a slow remote stall liveness.

The heartbeat is only as good as its cadence: a beat that waits behind a hung
S3 PUT is a beat that did not happen, and the run reads ``stuck`` while it
trains. So the local copy is written inline (it is what local readers see, and
it is cheap), and the remote copy goes to a :class:`Coalescing` worker — only
the newest pending state is uploaded, in order, so the final state can never be
overwritten by an older heartbeat that was still in flight.

Two attempts of one run (speculative duplicates, a pod resumed next to a live
one) share its ``run_state.yml``. A heartbeat reads the stored state first and
is dropped when another attempt has finished the run, so the losing duplicate
never flips it back to running. Best-effort: the read and the write are not
atomic, so a final state landing between them is overwritten once (the next
beat then sees its own state and carries on).
"""
import logging

import yaml

from vmn_exp.core.background import Coalescing
from vmn_exp.core.status import RUN_STATE_FILE, load_run_state
from vmn_exp.storage.cached import CachedSnapshotStorage, local_side

_LOGGER = logging.getLogger(__name__)


def split_storage(storage, app_name, verstr):
    """``(inline, remote target or None)`` of *storage* for one run's state
    writes; the target is called for the store to upload to (None: none yet).

    A local-first cache with a remote is split into its local side and its
    remote — written only once the remote is known to hold this run
    (:meth:`CachedSnapshotStorage.remote_for`, whose check may be a GET, so it
    runs in the background too). A store that is remote only is written
    entirely in the background; anything else (a local store, or a caller's
    own wrapper) is written inline, as given.
    """
    local = local_side(storage)
    if not getattr(storage, "is_remote", lambda: False)():
        return local, None
    if isinstance(storage, CachedSnapshotStorage):
        return local, lambda: storage.remote_for(app_name, verstr)
    return None, lambda: storage


def finished_by_another(stored, attempt):
    """Whether *stored* is a final state that *attempt* did not write."""
    return bool(stored) and stored.get("state") == "finished" and (
        stored.get("attempt") != attempt
    )


class RunStatePublisher:
    """Writes one run's state: inline locally, latest-wins in order remotely."""

    def __init__(self, storage, app_name, verstr, gate=None):
        self._storage = storage
        self._inline, self._remote_target = split_storage(storage, app_name, verstr)
        self._split = self._inline is not storage
        self._where = (app_name, verstr, RUN_STATE_FILE)
        # Sides this attempt has written its own state to: only there can a
        # stored final state be another attempt's.
        self._written = set()
        self.superseded = False
        self._remote = None
        if self._remote_target is not None:
            upload = gate.wrap(self._upload) if gate is not None else self._upload
            self._remote = Coalescing(upload, "vmn-run-state")

    def publish(self, state, heartbeat=False):
        """Write *state* now locally; queue it for the remote. Raises on a
        failed local write, like the storage call it replaces. A *heartbeat*
        is dropped, and :attr:`superseded` set, where another attempt has
        finished the run, and so is every heartbeat after that."""
        if heartbeat and self.superseded:
            return
        data = yaml.dump(state, sort_keys=False)
        attempt = state.get("attempt") if heartbeat else None
        if self._inline is not None:
            if heartbeat and self._stale(self._inline, attempt):
                return
            refused = self._inline.save_file(*self._where, data) is False
            if refused and self._split:
                # The record exists only remotely so far (a run resumed on
                # another host): the full store fetches it, then writes both.
                self._storage.save_file(*self._where, data)
                return
            self._written.add(id(self._inline))
        if self._remote is not None:
            self._remote.submit((data, heartbeat, attempt))

    def _upload(self, item):
        data, heartbeat, attempt = item
        target = self._remote_target()
        if target is None or (heartbeat and self._stale(target, attempt)):
            return
        target.save_file(*self._where, data)
        self._written.add(id(target))

    def _stale(self, side, attempt):
        if id(side) not in self._written:
            return False
        if not finished_by_another(load_run_state(side, *self._where[:2]), attempt):
            return False
        if not self.superseded:
            self.superseded = True
            _LOGGER.warning(
                f"vmn: run {self._where[1]} was finished by another attempt; "
                "this attempt stops heartbeating"
            )
        return True

    def close(self, timeout):
        """Upload what is pending, then stop. False if that did not finish."""
        return self._remote.close(timeout) if self._remote is not None else True
