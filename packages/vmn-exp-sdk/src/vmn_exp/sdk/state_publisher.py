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

A *final* state (finish, release) is held to that rule without the gap: it
is a compare-and-swap (:mod:`vmn_exp.core.state_cas`), dropped — and
:attr:`superseded` set — when another attempt finished the run first.

A remote that hands back a version token (S3/Azure ETag, GCS generation)
spares that read: a beat after this attempt's own write is a conditional PUT
on the token, which lands only while nobody else wrote the file; refused, the
beat falls back to the read. That halves a live run's state requests.
"""
import logging

import yaml

from vmn_exp.core.background import Coalescing
from vmn_exp.core.state_cas import (
    finished_by_another,
    save_if_match as _save,
    save_unless_finished_by_another,
    split_storage,
)
from vmn_exp.core.status import RUN_STATE_FILE, load_run_state

_LOGGER = logging.getLogger(__name__)


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
        # Remote side -> the token of this attempt's last write there.
        self._tokens = {}
        self.superseded = False
        self._remote = None
        if self._remote_target is not None:
            upload = gate.wrap(self._upload) if gate is not None else self._upload
            self._remote = Coalescing(upload, "vmn-run-state")

    def publish(self, state, heartbeat=False, final=False):
        """Write *state* now locally; queue it for the remote. Raises on a
        failed local write, like the storage call it replaces. A *heartbeat*
        is dropped, and :attr:`superseded` set, where another attempt has
        finished the run, and so is every heartbeat after that; so is a
        *final* state, there and on every side after."""
        if heartbeat and self.superseded:
            return
        data = yaml.dump(state, sort_keys=False)
        attempt = state.get("attempt") if heartbeat else None
        if self._inline is not None:
            if heartbeat and self._stale(self._inline, attempt):
                return
            if final and id(self._inline) in self._written:
                if not self._save_final(self._inline, state):
                    return
            elif not self._write_inline(data):
                return
        if self._remote is not None:
            self._remote.submit((data, heartbeat, attempt, dict(state) if final else None))

    def _write_inline(self, data):
        """Whether the remote still gets *data* (the full store wrote it all)."""
        refused = self._inline.save_file(*self._where, data) is False
        if refused and self._split:
            # The record exists only remotely so far (a run resumed on
            # another host): the full store fetches it, then writes both.
            self._storage.save_file(*self._where, data)
            return False
        self._written.add(id(self._inline))
        return True

    def _save_final(self, side, state):
        if save_unless_finished_by_another(side, *self._where, state):
            return True
        self._supersede("its final state is dropped")
        return False

    def _upload(self, item):
        data, heartbeat, attempt, final = item
        target = self._remote_target()
        if target is None:
            return
        if final is not None and id(target) in self._written:
            self._save_final(target, final)
            return
        token = self._tokens.pop(id(target), None)
        if heartbeat and token is not None:
            written, token = _save(target, self._where, data, token)
            if written:
                self._remember(target, token)
                return
        if heartbeat and self._stale(target, attempt):
            return
        self._remember(target, _save(target, self._where, data)[1])

    def _remember(self, side, token):
        self._written.add(id(side))
        if token is not None:
            self._tokens[id(side)] = token

    def _stale(self, side, attempt):
        if id(side) not in self._written:
            return False
        if not finished_by_another(load_run_state(side, *self._where[:2]), attempt):
            return False
        self._supersede("this attempt stops heartbeating")
        return True

    def _supersede(self, consequence):
        if not self.superseded:
            self.superseded = True
            _LOGGER.warning(
                f"vmn: run {self._where[1]} was finished by another attempt; {consequence}"
            )

    def close(self, timeout):
        """Upload what is pending, then stop. False if that did not finish."""
        return self._remote.close(timeout) if self._remote is not None else True
