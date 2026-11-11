#!/usr/bin/env python3
"""Ship a run's log to its remote off the caller's thread.

Periodic syncs are routine: one that fails is caught up by the next, so its
failure stays at debug. The final sync is the run's last: it is retried until
it lands or :meth:`LogSync.close` gives up on it, which then returns False
with :attr:`LogSync.last_error` set.

*job* is called with no arguments. ``Run`` passes a method of its own that
calls ``vmn_exp.sdk.run.sync_to_remote`` at call time, so tests that patch
that name keep reaching the sync.
"""
import logging

from vmn_exp.core.background import Coalescing
from vmn_exp.core.best_effort import quiet
from vmn_exp.core.final_retry import FinalRetry

_LOGGER = logging.getLogger(__name__)


class LogSync:
    """The ``vmn-exp-sync`` worker of one run; *gate* wraps each attempt,
    *abandon* (a ``threading.Event``) ends a final sync's retries."""

    def __init__(self, job, gate, abandon):
        self._attempt = gate.wrap(job)
        self._guard = quiet(_LOGGER)
        self._abandon = abandon
        self._final = FinalRetry(lambda _: self._attempt(), abandon.wait)
        self._final_submitted = False
        self._worker = Coalescing(self._sync, "vmn-exp-sync")

    def submit(self, final=False):
        self._final_submitted = self._final_submitted or final
        self._worker.submit(final)

    def _sync(self, final):
        if final:
            self._final.run(final)
        else:
            self._guard("experiment log sync", self._attempt)

    @property
    def last_error(self):
        """The last error of the final sync's attempts (None: none failed)."""
        return self._final.error

    def close(self, timeout):
        """Sync what is pending, then stop. False if that did not finish or
        the final sync did not land."""
        joined = self._worker.close(timeout)
        self._abandon.set()
        return joined and (self._final.landed or not self._final_submitted)
