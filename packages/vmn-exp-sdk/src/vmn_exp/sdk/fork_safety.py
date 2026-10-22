#!/usr/bin/env python3
"""Pause every open run's background threads around ``fork()``.

A thread mid storage call at ``fork()`` (a boto3/urllib3 pool lock, a logging
lock, an SDK lock held) leaves that lock held forever in the child, which can
then deadlock on it. Handlers registered once with ``os.register_at_fork``:

* before the fork, every open run of this process is paused
  (:meth:`~vmn_exp.sdk.background_gate.BackgroundGate.pause`), waiting for the
  calls in flight at most ``FORK_PAUSE_TIMEOUT_SEC`` in total — a hung S3 call
  delays the fork by that much, never forever, and is then forked through;
* after it, the parent resumes them;
* the child, which has none of the parent's threads and is not the parent
  runs' writer (``Run.pid``), gets clean gates, log-buffer locks and the
  open-run registry lock.

The module helpers pause the same set by hand.
"""
import contextlib
import os
import threading
import time

from vmn_exp.sdk import context

FORK_PAUSE_TIMEOUT_SEC = 10.0

# Forking thread -> the runs its before-handler paused (threads may fork at once).
_paused_for_fork = {}


def _open_runs():
    # No registry lock: another thread may hold it at fork time.
    return [r for r in list(context._OPEN_RUNS) if context._is_open_here(r)]


def _pause(runs, timeout):
    """Pause *runs* within *timeout* seconds in total (None: no limit)."""
    deadline = None if timeout is None else time.monotonic() + timeout
    quiesced = True
    for run in runs:
        left = None if deadline is None else max(0.0, deadline - time.monotonic())
        quiesced = run.pause_background(left) and quiesced
    return quiesced


def pause_background(timeout=None):
    """Pause the background threads of every open run of this process; wait
    up to *timeout* seconds in total (None: no limit). True if quiesced."""
    return _pause(_open_runs(), timeout)


def resume_background():
    """Undo one :func:`pause_background` on every open run."""
    for run in _open_runs():
        run.resume_background()


@contextlib.contextmanager
def background_paused(timeout=None):
    """``with background_paused():`` — every open run paused inside."""
    runs = _open_runs()
    try:
        yield _pause(runs, timeout)
    finally:
        for run in runs:
            run.resume_background()


def _before_fork():
    runs = _open_runs()
    _pause(runs, FORK_PAUSE_TIMEOUT_SEC)
    _paused_for_fork[threading.get_ident()] = runs


def _after_fork_in_parent():
    for run in _paused_for_fork.pop(threading.get_ident(), ()):
        run.resume_background()


def _after_fork_in_child():
    _paused_for_fork.clear()
    context._LOCK = threading.RLock()
    for run in list(context._OPEN_RUNS):
        after_fork = getattr(run, "_after_fork_in_child", None)
        if after_fork is not None:
            after_fork()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_before_fork,
        after_in_parent=_after_fork_in_parent,
        after_in_child=_after_fork_in_child,
    )
