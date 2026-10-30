#!/usr/bin/env python3
"""Publish a run's ``run_state.yml`` without letting a slow remote stall liveness.

The heartbeat is only as good as its cadence: a beat that waits behind a hung
S3 PUT is a beat that did not happen, and the run reads ``stuck`` while it
trains. So the local copy is written inline (it is what local readers see, and
it is cheap), and the remote copy goes to a :class:`Coalescing` worker — only
the newest pending state is uploaded, in order, so the final state can never be
overwritten by an older heartbeat that was still in flight.

Two attempts of one run (speculative duplicates, a pod resumed next to a live
one) share its ``run_state.yml``, and every write of it — each heartbeat, the
first write of a resumed attempt, a final state — is a compare-and-swap
(:mod:`vmn_exp.core.state_cas`) that is dropped, and :attr:`superseded` set,
when another attempt finished the run: the losing duplicate never flips it
back to running, nor erases its exit code. The one final state an attempt may
replace is the one it resumes, on its first write to each side.

The compare costs no read while this attempt's own last write is current: a
beat is a conditional write on that write's version token (S3/Azure ETag, GCS
generation, a local content hash, checked under the record's state lock) —
one PUT per beat remotely. Refused, it reads the state and decides again.
"""
import logging

from vmn_exp.core.background import Coalescing
from vmn_exp.core.state_cas import (
    compare_and_save_token,
    finished_by_another,
    pull_record,
    split_storage,
)
from vmn_exp.core.status import RUN_STATE_FILE

_LOGGER = logging.getLogger(__name__)


class RunStatePublisher:
    """Writes one run's state: inline locally, latest-wins in order remotely.

    *resumes* is the stored state the attempt resumes (None: a new run)."""

    def __init__(self, storage, app_name, verstr, gate=None, resumes=None):
        self._storage = storage
        self._inline, self._remote_target = split_storage(storage, app_name, verstr)
        self._split = self._inline is not storage
        self._where = (app_name, verstr, RUN_STATE_FILE)
        self._resumes = resumes
        # Sides this attempt has written its own state to: only there can a
        # stored final state not be the one it resumes.
        self._written = set()
        # Side -> (state, token) of this attempt's last write there.
        self._tokens = {}
        self.superseded = False
        self._remote = None
        if self._remote_target is not None:
            upload = gate.wrap(self._upload) if gate is not None else self._upload
            self._remote = Coalescing(upload, "vmn-run-state")

    def publish(self, state, heartbeat=False, final=False):
        """Write *state* now locally; queue it for the remote. Raises on a
        failed local write, like the storage call it replaces. Dropped, and
        :attr:`superseded` set, where another attempt has finished the run;
        so is every heartbeat after that."""
        if heartbeat and self.superseded:
            return
        state = dict(state)
        if self._inline is not None:
            if not self._holds_record() or not self._save(self._inline, state, final):
                return
        if self._remote is not None:
            self._remote.submit((state, final))

    def _holds_record(self):
        """Whether the local side may be written: a record only the remote
        holds so far (a run resumed on another host) is fetched first."""
        if not self._split or id(self._inline) in self._written:
            return True
        pull_record(self._storage, self._inline, *self._where[:2])
        return self._inline.exists(*self._where[:2])

    def _upload(self, item):
        state, final = item
        target = self._remote_target()
        if target is None or (self.superseded and not final):
            return
        if not self._save(target, state, final) and final:
            self._cache_winner(target)

    def _save(self, side, state, final):
        """Whether *state* landed on *side*."""
        written, token = compare_and_save_token(
            side, self._where, self._unless_lost(side, state), self._tokens.get(id(side)))
        if written is None:
            self._supersede("its final state is dropped" if final
                            else "this attempt stops heartbeating")
            return False
        self._written.add(id(side))
        self._tokens[id(side)] = (state, token) if token is not None else None
        return True

    def _unless_lost(self, side, state):
        attempt = state.get("attempt")
        first = id(side) not in self._written

        def update(stored):
            lost = finished_by_another(stored, attempt) and not (
                first and self._resumed(stored))
            return None if lost else state

        return update

    def _resumed(self, stored):
        """Whether *stored* is the final state this attempt resumes."""
        return bool(self._resumes) and self._resumes.get("state") == "finished" and (
            stored.get("attempt") == self._resumes.get("attempt"))

    def _cache_winner(self, target):
        """Replace this attempt's local final state with the remote's winner."""
        data = target.load_file(*self._where) if self._inline is not None else None
        if data:
            self._inline.save_file(*self._where, data)

    def _supersede(self, consequence):
        if not self.superseded:
            self.superseded = True
            _LOGGER.warning(
                f"vmn: run {self._where[1]} was finished by another attempt; {consequence}"
            )

    def close(self, timeout):
        """Upload what is pending, then stop. False if that did not finish."""
        return self._remote.close(timeout) if self._remote is not None else True
