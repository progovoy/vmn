#!/usr/bin/env python3
"""``vmn-exp run``'s run-state writes, and the budget of its final uploads.

A heartbeat that waits behind a hung remote PUT is a supervise loop that
ingests no metrics and kills no child past its grace period. So the local
copy of the state is written inline (cheap, and what local readers see) and
the remote copy goes to a :class:`Coalescing` worker, newest wins, in order:
an older beat never lands after the final state. A failed beat upload is
repaired by the next beat; the final state's is retried until it lands or
:meth:`StateUploads.close` gives up on it. The remote write is unconditional,
as it always was for the supervisor (the SDK's is a compare-and-swap).
"""

from vmn_exp.cli.supervisor import Abandonable
from vmn_exp.core.background import Coalescing
from vmn_exp.core.final_retry import FinalRetry
from vmn_exp.core.state_cas import dump_state, split_storage
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.cached import is_log_buffer, local_side

# After a signal the child's wait and the final uploads share a pod's default
# grace period (30 s) with room to spare; the child gets what the uploads
# leave unless its kill grace was set explicitly.
SIGNAL_BUDGET_SEC = 25
SIGNAL_UPLOAD_SEC = 10
SIGNAL_CHILD_GRACE_SEC = SIGNAL_BUDGET_SEC - SIGNAL_UPLOAD_SEC


class StateUploads:
    """One run's ``run_state.yml``: inline locally, latest-wins remotely.

    *wait* is the pause between the final upload's retries; *guard* runs a
    beat's upload (a :class:`BestEffort`: warn once, then debug)."""

    def __init__(self, storage, app_name, verstr, wait, guard):
        self._storage = storage
        self._where = (app_name, verstr, RUN_STATE_FILE)
        self._local, self._target = split_storage(storage, app_name, verstr)
        self._has_home = self._local is storage
        self._guard = guard
        self._abandon = Abandonable(wait)
        self._final = FinalRetry(self._upload_once, self._abandon.wait)
        self._final_submitted = False
        self._remote = None
        if self._target is not None:
            self._remote = Coalescing(self._upload, "vmn-run-state")

    def publish(self, run_state, final=False):
        """Write *run_state* locally, then queue it for the remote (raises
        on a failed local write, like the storage call it replaces, and then
        queues nothing: the remote never holds a state the local copy lacks)."""
        data = dump_state(run_state)
        if self._local is not None and self._holds_record():
            self._local.save_file(*self._where, data)
        if self._remote is not None:
            self._final_submitted = self._final_submitted or final
            self._remote.submit((data, final))

    def _holds_record(self):
        """Whether the local side may be written: never a record that exists
        nowhere (it would come back as a zombie); one only the remote holds
        is fetched first."""
        if not self._has_home:
            self._has_home = self._storage.ensure_local_record(*self._where[:2])
        return self._has_home

    def _upload(self, item):
        data, final = item
        if final:
            self._final.run(data)
        else:
            self._guard("run state upload", self._upload_once, data)

    def _upload_once(self, data):
        target = self._target()
        if target is not None:
            target.save_file(*self._where, data)

    @property
    def last_error(self):
        """The last error of the final state's upload attempts (None: none failed)."""
        return self._final.error

    def close(self, timeout):
        """Upload what is pending, then stop. False if that did not finish
        or the final state did not land."""
        if self._remote is None:
            return True
        joined = self._remote.close(timeout)
        self._abandon.set()
        return joined and (self._final.landed or not self._final_submitted)


def final_upload_deadline(now, timeout, signalled_at, signal_grace):
    """When the final uploads are given up: *timeout* from *now*, or, after a
    signal, *signal_grace* (the child's wait) plus the uploads' share of the
    signal budget from the signal."""
    if signalled_at is None:
        return now + timeout
    return signalled_at + signal_grace + SIGNAL_UPLOAD_SEC


def finish_uploads(sync, state_uploads, deadline, clock):
    """Spend one budget on the final log sync, then on the final state.
    Whether the final state landed."""
    sync.final(max(0.0, deadline - clock()))
    return state_uploads.close(max(0.0, deadline - clock()))


def not_uploaded_warning(verstr, error, storage):
    """The warning for a final state that did not reach the remote, with the
    way to upload it later where there is one: ``vmn-exp push`` reads a
    checkout's local copy, never a log buffer."""
    reason = f": {error}" if error is not None else " in time"
    hint = ""
    if local_side(storage) is not None and not is_log_buffer(storage):
        hint = "; run `vmn-exp push` to upload it"
    return f"Experiment {verstr}: the final run state was not uploaded{reason}{hint}"
