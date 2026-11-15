#!/usr/bin/env python3
"""The SDK's process-wide hooks, installed at the first run open.

Importing ``vmn_exp.sdk`` (to read runs, say) must leave the process alone.
Only once a run is open does the SDK chain ``sys.excepthook`` (an uncaught
exception marks the abandoned run failed) and register its atexit finalizer.
Registering then, after the run's storage module was imported, also makes
the finalizer run before that storage's own exit flush (atexit is LIFO), so
the flush ships what the finalizer wrote.
"""
import threading


class ProcessHooks:
    """Installs the hooks once per process (*getpid* tells a forked child)."""

    def __init__(self, getpid):
        self._getpid = getpid
        self._installed_pid = None
        self._lock = threading.Lock()

    def install_once(self, sys_module, atexit_module, finalize, note_uncaught):
        with self._lock:
            pid = self._getpid()
            if pid == self._installed_pid:
                return
            self._installed_pid = pid
            _chain_excepthook(sys_module, note_uncaught)
            atexit_module.register(finalize)


def _chain_excepthook(sys_module, note_uncaught):
    previous = sys_module.excepthook

    def excepthook(exc_type, exc_value, tb):
        note_uncaught(exc_value)
        previous(exc_type, exc_value, tb)

    sys_module.excepthook = excepthook
