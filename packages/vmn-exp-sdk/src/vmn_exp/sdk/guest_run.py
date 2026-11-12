"""The run a script started by ``vmn-exp run`` adopts: a guest on the
supervisor's record (plan 38 A5).

One record, two processes, two streams. The supervisor stays the only writer
of the run's state (heartbeat, exit code, final state), its ``run`` entry,
``output.log`` and the failure alert. The guest appends only to a stream of
its own, ``<writer id>-sdk~<owner>``, and syncs and compacts that stream like
any run does its own; it writes no run state, no ``run`` entry and fires no
finish alerts. The run's result is the process's exit code, as the
supervisor sees it.
"""
import logging

from vmn_exp.core.streams import guest_writer_id
from vmn_exp.core.writer import process_writer_id
from vmn_exp.sdk import adoption
from vmn_exp.sdk.run import Run

_LOGGER = logging.getLogger(__name__)


class GuestRun(Run):
    """A :class:`Run` that records into a run another process owns the state
    of, as *writer* (default: this process's writer id with ``-sdk``).
    ``name`` comes from ``vmn-exp run --name`` and ``capture_output`` is the
    supervisor's: both are ignored here."""

    def __init__(self, *args, name=None, capture_output=False, writer=None, **kwargs):
        if name is not None:
            _LOGGER.warning("vmn: start_run(name=...) is ignored in the run vmn-exp run "
                            "started; name it with vmn-exp run --name")
        if capture_output:
            _LOGGER.debug("vmn: capture_output is ignored; vmn-exp run captures the output")
        super().__init__(*args, name=None, capture_output=False,
                         writer=writer or guest_writer_id(process_writer_id()), **kwargs)

    def _publish(self, updates=(), final=False):
        pass  # the supervisor writes the run's state

    def _publish_heartbeat(self):
        pass  # the heartbeat thread still flushes and syncs the guest's stream

    def _record_final(self, exit_code, deadline, error=None, media_share=1.0, **final_state):
        return self._close_attempt(deadline, lambda: self._error_only(error),
                                   media_share=media_share)

    def _record_release(self, deadline, reason=None, signal=None, media_share=1.0):
        return self._close_attempt(deadline, lambda: self._error_only(None),
                                   media_share=media_share)

    def _error_only(self, error):
        """The guest's outcome: the ``error`` entry, when given; no state."""
        if error is not None:
            self._record_guard("error", self._record_error, error)
        return {}


def adopted_record(app_name, storage, parent, nested, fork_from, active, env, getppid,
                   locate, consume):
    """``(app_name, storage, verstr, exp_conf)`` of the run ``vmn-exp run``
    offers this process in the Env *env* (:func:`vmn_exp.sdk.adoption.requested`;
    a granted offer is consumed with ``consume(names)``), found with
    *locate* (``resume.locate``); None when there is none to take, or when
    the store this process resolved does not hold it — then with a warning,
    and the caller creates its own run as without the offer."""
    verstr = adoption.requested(dict(env), getppid, parent, nested, fork_from, active)
    if verstr is None:
        return None
    consume((adoption.ADOPT_RUN_ID_ENV, adoption.ADOPT_PID_ENV))
    try:
        app_name, storage, verstr, _, exp_conf = locate(app_name, verstr, storage,
                                                        action="adopt", env=env)
    except ValueError as exc:
        _LOGGER.warning(f"vmn: not recording into run {verstr} of vmn-exp run: {exc}. "
                        "This process resolved a store without it (give it the "
                        "supervisor's store); a run of its own is created instead. "
                        "vmn-exp run --no-adopt or VMN_EXP_ADOPT=0 skip the offer.")
        return None
    return app_name, storage, verstr, exp_conf
