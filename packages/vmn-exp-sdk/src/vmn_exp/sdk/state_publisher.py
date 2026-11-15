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

A failed upload is never silent: a heartbeat's warns once (the next beat
repairs it), the final state's is retried until it lands or :meth:`close`
gives up on it, which then returns False with :attr:`last_error` set.
"""
import logging
import threading

from vmn_exp.core.background import Coalescing
from vmn_exp.core.best_effort import BestEffort
from vmn_exp.core.final_retry import FinalRetry
from vmn_exp.core.state_cas import (
    compare_and_save_token,
    dump_state,
    finished_by_another,
    split_storage,
)
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.base import NO_FILE

_LOGGER = logging.getLogger(__name__)


class RunStatePublisher:
    """Writes one run's state: inline locally, latest-wins in order remotely.

    *resumes* is the stored state the attempt resumes (None: a new run).
    *abandon* (a ``threading.Event``) is what a failing final upload waits
    on between attempts; :meth:`close` sets it to stop retrying."""

    def __init__(self, storage, app_name, verstr, gate=None, resumes=None, abandon=None):
        self._storage = storage
        self._inline, self._remote_target = split_storage(storage, app_name, verstr)
        self._where = (app_name, verstr, RUN_STATE_FILE)
        self._resuming = bool(resumes)
        # The final state this attempt resumes, if any, it may replace once.
        self._resumes_final = self._resuming and resumes.get("state") == "finished"
        self._resumed_attempt = resumes.get("attempt") if self._resumes_final else None
        # Side -> token (None: the side has none) of this attempt's last
        # write there; only on a side it has written can a stored final
        # state not be the one it resumes.
        self._tokens = {}
        self.superseded = False
        self._final_submitted = False
        self._abandon = abandon if abandon is not None else threading.Event()
        # Gated per attempt, never across a final retry's waits: a fork
        # (fork_safety) must not be held for the whole retry.
        self._attempt = gate.wrap(self._upload_once) if gate is not None else self._upload_once
        self._final = FinalRetry(self._attempt, self._abandon.wait)
        self._beat_guard = BestEffort(
            _LOGGER, lambda what, exc: f"vmn: could not upload the state of run {verstr}: {exc}")
        self._remote = None
        if self._remote_target is not None:
            self._remote = Coalescing(self._upload, "vmn-run-state")

    def publish(self, state, heartbeat=False, final=False):
        """Write *state* now locally; queue it for the remote. Raises on a
        failed local write, like the storage call it replaces. Dropped, and
        :attr:`superseded` set, where another attempt has finished the run;
        so is every heartbeat after that."""
        if heartbeat and self.superseded:
            return
        state = dict(state)
        dumped = (state, dump_state(state))
        if self._inline is not None:
            if not self._holds_record() or not self._save(self._inline, dumped, final):
                return
        if self._remote is not None:
            self._final_submitted = self._final_submitted or final
            self._remote.submit((dumped, final))

    def _holds_record(self):
        """Whether the local side may be written: a record only the remote
        holds so far (a run resumed on another host, or on a fresh log
        buffer) gets a home there first — the storage's own, for a buffer
        only the record's metadata."""
        if id(self._inline) in self._tokens or self._inline is self._storage:
            return True
        app_name, verstr = self._where[:2]
        self._storage.ensure_local_record(app_name, verstr)
        if self._inline.exists(app_name, verstr):
            return True
        _LOGGER.debug(f"vmn: no record of {verstr} here or remotely; its state is dropped")
        return False

    def _upload(self, item):
        if item[1]:
            self._final.run(item)
        else:
            self._beat_guard("state upload", self._attempt, item)

    def _upload_once(self, item):
        dumped, final = item
        target = self._remote_target()
        if target is None or (self.superseded and not final):
            return
        if not self._save(target, dumped, final) and final:
            self._cache_winner(target)

    def _save(self, side, dumped, final):
        """Whether *dumped* — ``(state, its YAML)`` — landed on *side*."""
        written, token = compare_and_save_token(
            side, self._where, self._unless_lost(side, dumped[0]), self._seed(side), dumped)
        if written is None:
            self._supersede("its final state is dropped" if final
                            else "this attempt stops heartbeating")
            return False
        self._tokens[id(side)] = token
        return True

    def _seed(self, side):
        """The CAS's first round on *side*: the token of this attempt's last
        write there (its own state, which *update* keeps); before one, a new
        run's record (just claimed) holds no state yet, so its first write is
        a create, no read."""
        if id(side) in self._tokens or self._resuming:
            token = self._tokens.get(id(side))
            return ({}, token) if token is not None else None
        return {}, NO_FILE

    def _unless_lost(self, side, state):
        attempt = state.get("attempt")
        first = id(side) not in self._tokens

        def update(stored):
            resumed = self._resumes_final and stored.get("attempt") == self._resumed_attempt
            lost = finished_by_another(stored, attempt) and not (first and resumed)
            return None if lost else state

        return update

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

    @property
    def last_error(self):
        """The last error of the final state's upload attempts (None: none failed)."""
        return self._final.error

    def close(self, timeout):
        """Upload what is pending, then stop. False if that did not finish
        or the final state did not land (superseded counts as landed)."""
        if self._remote is None:
            return True
        joined = self._remote.close(timeout)
        self._abandon.set()
        return joined and (self._final.landed or self.superseded or not self._final_submitted)
