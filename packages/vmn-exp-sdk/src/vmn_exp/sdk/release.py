#!/usr/bin/env python3
"""Handing a run back unfinished: ``run.release()`` (plan 28 API2).

An evicted or preempted job is often retried by its orchestrator as the same
run (``start_run(run_id=...)``). Releasing ends this attempt's recording
cleanly — media uploads drained, the log flushed and synced, the heartbeat and
sampler stopped — without ending the run: ``run_state.yml`` says ``state:
released`` with no exit code, so the run derives as ``created`` (waiting) at
once instead of ``running`` until it goes ``stuck``, and settles as ``lost``
once its outer run has ended. ``start_run(on_sigterm="release")`` makes the
SDK's SIGTERM handler release such a run instead of failing it with 143;
``VMN_EXP_ON_SIGTERM`` sets that default for every run that passes none.
``sigterm_exit`` (``VMN_EXP_SIGTERM_EXIT``) is what the handler does next:
``"kill"`` re-delivers the signal, ``"raise"`` raises ``SystemExit(143)`` in
the main thread so ``finally`` blocks and context managers still run.
"""
import os

from vmn_exp._base import now_iso
from vmn_exp.core.status import RELEASED

FAIL, RELEASE = "fail", "release"
ON_SIGTERM = (FAIL, RELEASE)
ON_SIGTERM_ENV = "VMN_EXP_ON_SIGTERM"
KILL, RAISE = "kill", "raise"
SIGTERM_EXIT = (KILL, RAISE)
SIGTERM_EXIT_ENV = "VMN_EXP_SIGTERM_EXIT"


def resolve_on_sigterm(value):
    """*value*, else ``VMN_EXP_ON_SIGTERM``, else ``"fail"`` — validated."""
    return _resolve(value, ON_SIGTERM, "on_sigterm", ON_SIGTERM_ENV)


def resolve_sigterm_exit(value):
    """*value*, else ``VMN_EXP_SIGTERM_EXIT``, else ``"kill"`` — validated."""
    return _resolve(value, SIGTERM_EXIT, "sigterm_exit", SIGTERM_EXIT_ENV)


def _resolve(value, choices, name, env):
    """The first of *choices* is the default; a bad env value names *env*."""
    if value is None and os.environ.get(env):
        value, name = os.environ[env], env
    value = choices[0] if value is None else value
    if value not in choices:
        raise ValueError(f"{name} must be one of {', '.join(choices)}, not {value!r}")
    return value


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
