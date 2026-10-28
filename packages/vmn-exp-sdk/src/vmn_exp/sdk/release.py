#!/usr/bin/env python3
"""Handing a run back unfinished: ``run.release()`` (plan 28 API2).

An evicted or preempted job is often retried by its orchestrator as the same
run (``start_run(run_id=...)``). Releasing ends this attempt's recording
cleanly — media uploads drained, the log flushed and synced, the heartbeat and
sampler stopped — without ending the run: ``run_state.yml`` says ``state:
released`` with no exit code, so the run derives as ``created`` (waiting) at
once instead of ``running`` until it goes ``stuck``, and settles as ``lost``
once its outer run has ended. ``start_run(on_sigterm="release")`` makes the
SDK's SIGTERM handler release such a run instead of failing it with 143.
"""
from vmn_exp._base import now_iso
from vmn_exp.core.status import RELEASED

FAIL, RELEASE = "fail", "release"
ON_SIGTERM = (FAIL, RELEASE)


def check_on_sigterm(value):
    """ValueError unless *value* is a valid ``on_sigterm``."""
    if value not in ON_SIGTERM:
        raise ValueError(f"on_sigterm must be one of {', '.join(ON_SIGTERM)}, not {value!r}")


def released_state(duration_sec, reason=None, signal=None):
    """The run-state updates of a released attempt."""
    state = {
        "state": RELEASED,
        "end_reason": RELEASED,
        "released_at": now_iso(),
        "duration_sec": duration_sec,
    }
    if reason is not None:
        state["release_reason"] = str(reason)
    if signal is not None:
        state["signal"] = signal
    return state
