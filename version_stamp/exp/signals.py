#!/usr/bin/env python3
"""Finalize open SDK runs when the process is sent SIGTERM.

A preempted job (a spot reclaim, ``scancel``, a Kubernetes eviction) is sent
SIGTERM, and atexit handlers never run for a process a signal kills. Without
this the run would claim ``running`` until its heartbeat went stale.

The handler is installed only while a run is open, only from the main thread
(Python allows no other), and never over ``SIG_IGN`` — a process that ignores
SIGTERM survives it, so its runs did not end. When it fires it finalizes the
open runs, puts the previous handler back and hands the signal on: a Python
handler the workload installed is called, and the default disposition is
re-delivered so the process still dies of SIGTERM.
"""
import os
import signal
import threading

_HANDLED = signal.SIGTERM
# Only ever touched from the main thread (Python delivers signals there too),
# so there is no lock: the one "concurrent" caller is the handler itself.
_STATE = {"installed": False, "previous": None, "finalize": None}


def _on_main_thread():
    return threading.current_thread() is threading.main_thread()


def install(finalize):
    """Route SIGTERM through ``finalize(signum)`` first. Idempotent."""
    if not _on_main_thread():
        return
    if _STATE["installed"]:
        return
    previous = signal.getsignal(_HANDLED)
    # None: a handler installed outside Python, which cannot be chained.
    if previous is signal.SIG_IGN or previous is None:
        return
    _STATE.update(installed=True, previous=previous, finalize=finalize)
    signal.signal(_HANDLED, _handle)


def uninstall():
    """Put the previous handler back, unless someone replaced ours since."""
    if _on_main_thread():
        _restore()


def _restore():
    if not _STATE["installed"]:
        return
    if signal.getsignal(_HANDLED) is _handle:
        signal.signal(_HANDLED, _STATE["previous"])
    _STATE.update(installed=False, previous=None, finalize=None)


def _handle(signum, frame):
    # Read first: finishing the last open run uninstalls us, clearing the state.
    finalize, previous = _STATE["finalize"], _STATE["previous"]
    try:
        if finalize is not None:
            finalize(signum)
    finally:
        _restore()
        _chain(previous, signum, frame)


def _chain(previous, signum, frame):
    if callable(previous):
        previous(signum, frame)
    elif previous == signal.SIG_DFL:
        os.kill(os.getpid(), signum)
