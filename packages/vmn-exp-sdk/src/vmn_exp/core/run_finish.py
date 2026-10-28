#!/usr/bin/env python3
"""Finishing a run from outside it: ``vmn_exp.sdk.manage.finish_run`` and
``vmn-exp add --finish``.

An orchestrator that gives up on a pod, or closes a study's leftover trials,
writes the run's final ``run_state.yml`` itself instead of reopening the run
(which would heartbeat and read ``running`` first). The run's start, host and
heartbeat cadence are kept; ``exit_code``, ``finished_at``, ``duration_sec``
and the caller's ``error``/``end_reason`` replace the rest.

Refused unless forced: a run another attempt is still heartbeating (fresh by
the writer's clock or the store's, :func:`~vmn_exp.core.status.derive_status`)
and a run that already finished. The final state carries a new ``attempt``,
so a forced-out live attempt drops its next heartbeat instead of reopening
the run (:mod:`vmn_exp.sdk.state_publisher`).
"""
import uuid

from vmn_exp._base import now_iso
from vmn_exp.core.run_error import error_from_exception, error_from_message
from vmn_exp.core.status import (
    FAILED,
    RUNNING,
    SUCCEEDED,
    derive_status,
    load_run_state,
    parse_iso,
    run_state_observed_at,
)
from vmn_exp.core.writer import append_to_log, create_log_entry, flush_log, save_run_state

# What a previous ending left in the state; a new ending says its own.
_ENDING_FIELDS = ("error", "end_reason", "signal", "received_signal")


class FinishRefusedError(ValueError):
    """The run is live elsewhere or already finished; ``force`` finishes it anyway."""


def finish_run(storage, app_name, verstr, exit_code, error=None, end_reason=None,
               force=False):
    """Write *verstr*'s final run state; False when there is no such record.

    *error* — a message or an exception — becomes the state's ``error`` and an
    ``error`` log entry. Raises :class:`FinishRefusedError` (see the module
    doc) and ValueError for an *exit_code* that is not an int.
    """
    exit_code = _checked_exit_code(exit_code)
    if not storage.exists(app_name, verstr):
        return False
    prior = load_run_state(storage, app_name, verstr) or {}
    if not force:
        _refuse_unfinishable(prior, run_state_observed_at(storage, app_name, verstr), verstr)
    recorded = None if error is None else _error_mapping(error)
    if recorded is not None:
        append_to_log(storage, app_name, verstr,
                      create_log_entry("error", message=recorded["message"]))
        flush_log(storage, app_name, verstr)
    save_run_state(storage, app_name, verstr,
                   final_state(prior, exit_code, recorded, end_reason))
    return True


def final_state(prior, exit_code, error=None, end_reason=None):
    """*prior* (a run state, maybe empty) ended with *exit_code*."""
    state = {k: v for k, v in prior.items() if k not in _ENDING_FIELDS}
    finished_at = now_iso()
    state.update(
        state="finished",
        exit_code=exit_code,
        finished_at=finished_at,
        duration_sec=_duration(prior.get("started_at"), finished_at),
        attempt=uuid.uuid4().hex[:12],
    )
    if error is not None:
        state["error"] = error
    if end_reason:
        state["end_reason"] = str(end_reason)
    return state


def _checked_exit_code(exit_code):
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise ValueError(f"exit_code must be an int, got {exit_code!r}")
    return exit_code


def _refuse_unfinishable(prior, observed_at, verstr):
    status = derive_status(prior, observed_at=observed_at)
    if status == RUNNING:
        raise FinishRefusedError(
            f"Run '{verstr}' is still heartbeating (attempt {prior.get('attempt')} "
            f"on {prior.get('host')}); pass force to finish it anyway")
    if status in (SUCCEEDED, FAILED):
        raise FinishRefusedError(
            f"Run '{verstr}' already finished ({status}, exit code "
            f"{prior.get('exit_code')}); pass force to finish it again")


def _error_mapping(error):
    if isinstance(error, BaseException):
        return error_from_exception(error)
    return error_from_message(error)


def _duration(started_at, finished_at):
    started, finished = parse_iso(started_at), parse_iso(finished_at)
    if started is None or finished is None:
        return None
    return round((finished - started).total_seconds(), 3)
