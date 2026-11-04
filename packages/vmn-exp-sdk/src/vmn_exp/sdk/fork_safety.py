#!/usr/bin/env python3
"""Pause every open run's background threads around ``fork()``.

A thread mid storage call at ``fork()`` (a boto3/urllib3 pool lock, a logging
lock, an SDK lock held) leaves that lock held forever in the child, which can
then deadlock on it. Handlers registered once with ``os.register_at_fork``:

* before the fork, every run of this process is paused — the open ones and
  those still finishing (from ``finish()`` until its final uploads are done,
  ``context._CLOSING`` once it left the registry) —
  (:meth:`~vmn_exp.sdk.background_gate.BackgroundGate.pause`), waiting for the
  calls in flight at most ``FORK_PAUSE_TIMEOUT_SEC`` in total — a hung S3 call
  delays the fork by that much, never forever, and is then forked through;
* after it, the parent resumes them;
* the child, which has none of the parent's threads and is not the parent
  runs' writer (``Run.pid``: an inherited run records nothing there), gets
  clean gates, log-buffer locks and the open-run registry lock, and no
  finishing runs.

The module helpers pause the open runs by hand. ``PROCESS_GATE`` gates the
background calls no run owns (the sysmetrics init thread's ``nvmlInit``); only
a fork pauses it, within the same budget.
"""
import contextlib
import os
import threading
import time

from vmn_exp.sdk import context
from vmn_exp.sdk.background_gate import BackgroundGate

FORK_PAUSE_TIMEOUT_SEC = 10.0

PROCESS_GATE = BackgroundGate()

# Forking thread -> the gates its before-handler paused (threads may fork at once).
_paused_for_fork = {}


def _open_runs():
    # No registry lock: another thread may hold it at fork time.
    return [r for r in list(context._OPEN_RUNS) if context._is_open_here(r)]


def _fork_runs():
    """Every run of this process with background calls that may be in flight:
    open, finishing (still registered or already ``_CLOSING``) or detaching.
    A finishing run's released gate admits every call, but pausing it still
    waits for the ones in flight."""
    # Unlocked reads: a run moving to _CLOSING meanwhile may show up twice.
    runs = list(context._OPEN_RUNS) + list(context._CLOSING)
    return list({id(r): r for r in runs if context._is_mine(r)}.values())


def _gates(runs):
    return [run._gate for run in runs]


def _pause(gates, timeout):
    """Pause *gates* within *timeout* seconds in total (None: no limit)."""
    deadline = None if timeout is None else time.monotonic() + timeout
    quiesced = True
    for gate in gates:
        left = None if deadline is None else max(0.0, deadline - time.monotonic())
        quiesced = gate.pause(left) and quiesced
    return quiesced


def _resume(gates):
    for gate in gates:
        gate.resume()


def pause_background(timeout=None):
    """Pause the background threads of every open run of this process; wait
    up to *timeout* seconds in total (None: no limit). True if quiesced."""
    return _pause(_gates(_open_runs()), timeout)


def resume_background():
    """Undo one :func:`pause_background` on every open run."""
    _resume(_gates(_open_runs()))


@contextlib.contextmanager
def background_paused(timeout=None):
    """``with background_paused():`` — every open run paused inside."""
    gates = _gates(_open_runs())
    try:
        yield _pause(gates, timeout)
    finally:
        _resume(gates)


def _before_fork():
    gates = _gates(_fork_runs()) + [PROCESS_GATE]
    _pause(gates, FORK_PAUSE_TIMEOUT_SEC)
    _paused_for_fork[threading.get_ident()] = gates


def _after_fork_in_parent():
    _resume(_paused_for_fork.pop(threading.get_ident(), ()))


def _after_fork_in_child():
    _paused_for_fork.clear()
    context._LOCK = threading.RLock()
    PROCESS_GATE.after_fork_in_child()
    for run in list(context._OPEN_RUNS) + list(context._CLOSING):
        after_fork = getattr(run, "_after_fork_in_child", None)
        if after_fork is not None:
            after_fork()
    context._CLOSING.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_before_fork,
        after_in_parent=_after_fork_in_parent,
        after_in_child=_after_fork_in_child,
    )
