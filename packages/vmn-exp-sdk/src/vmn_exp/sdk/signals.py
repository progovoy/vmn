#!/usr/bin/env python3
"""Finalize open SDK runs when the process is sent SIGTERM.

A preempted job (a spot reclaim, ``scancel``, a Kubernetes eviction) is sent
SIGTERM, and atexit handlers never run for a process a signal kills. Without
this the run would claim ``running`` until its heartbeat went stale.

Only the main thread may install a handler, yet runs are often opened from
worker threads (a thread-pool sweep). So the handler is installed when
``vmn_exp.sdk`` is imported on the main thread (and again by a main-thread
``start_run()`` if the workload replaced it since), and stays: with no open
run it finalizes nothing. It is never installed over ``SIG_IGN`` — a process
that ignores SIGTERM survives it, so its runs did not end. When it fires it
finalizes the open runs, puts the previous handler back and hands the signal
on: a Python handler the workload installed is called, and the default
disposition is re-delivered so the process still dies of SIGTERM.
"""
import os
import signal
import threading

_HANDLED = signal.SIGTERM
# Only ever touched from the main thread (Python delivers signals there too),
# so there is no lock: the one "concurrent" caller is the handler itself.
_STATE = {"previous": None, "finalize": None, "timeout": None}


def _on_main_thread():
    return threading.current_thread() is threading.main_thread()


def install(finalize, timeout):
    """Route SIGTERM through ``finalize(signum)`` first, waiting at most
    ``timeout()`` seconds for it (read when the signal arrives). Idempotent; chains whatever handler is current,
    so it can be called again after the workload installed its own."""
    if not _on_main_thread():
        return
    previous = signal.getsignal(_HANDLED)
    # None: a handler installed outside Python, which cannot be chained.
    if previous in (_handle, signal.SIG_IGN, None):
        return
    _STATE.update(previous=previous, finalize=finalize, timeout=timeout)
    signal.signal(_HANDLED, _handle)


def _handle(signum, frame):
    previous = _STATE["previous"]
    try:
        _run_bounded(_STATE["finalize"], signum, _STATE["timeout"]())
    finally:
        if signal.getsignal(_HANDLED) is _handle:
            signal.signal(_HANDLED, previous)
        _chain(previous, signum, frame)


def _run_bounded(finalize, signum, timeout):
    # On a daemon thread: the handler interrupts the main thread wherever it
    # was, possibly holding a lock *finalize* needs, and a signaled process has
    # a grace period to die within.
    worker = threading.Thread(target=finalize, args=(signum,), daemon=True)
    worker.start()
    worker.join(timeout=timeout)


def _chain(previous, signum, frame):
    if callable(previous):
        previous(signum, frame)
    elif previous == signal.SIG_DFL:
        os.kill(os.getpid(), signum)
