#!/usr/bin/env python3
"""Which experiment run the calling code is running inside.

One process may hold several open runs at once — nested ``start_run()`` calls,
or a thread-pool sweep that opens one run per trial. Three things must stay
straight when it does:

* **the current run** of a piece of code: the run its own context opened (a
  ``ContextVar``, so each thread sees its own), else the process's only open run;
* **fork safety**: a forked child inherits the parent's run objects, but they are
  not open *in the child* — only runs created by this pid count;
* **the environment** exported for subprocesses (``VMN_EXPERIMENT_ID``,
  ``VMN_APP_NAME``): it names the most recently opened run still open, and once
  the last one closes it is exactly what it was before the first one opened —
  however out of order the runs finished.
"""
import contextvars
import os
import threading

from version_stamp.exp import APP_NAME_ENV

EXPERIMENT_ID_ENV = "VMN_EXPERIMENT_ID"
_ENV_KEYS = (EXPERIMENT_ID_ENV, APP_NAME_ENV)

# Every run ever registered and not yet closed, oldest first. Filtered by pid on
# read, so entries a forked child inherited are invisible to it.
_OPEN_RUNS = []
_LOCK = threading.RLock()
_CURRENT = contextvars.ContextVar("vmn_current_run", default=None)
# The exported env as it was before this process opened its first run.
_BASELINE = {"pid": None, "env": {}}


def _is_open_here(run):
    if run is None or getattr(run, "_finished", False):
        return False
    return getattr(run, "pid", os.getpid()) == os.getpid()


def open_runs():
    """This process's open runs, oldest first."""
    with _LOCK:
        return [r for r in _OPEN_RUNS if _is_open_here(r)]


def current_run():
    """The run the calling context should record into, or None.

    The run opened by the calling context (thread) if it is still open, else the
    process's only open run. With several open runs and none bound to this
    context the answer is ambiguous, so it is None.
    """
    run = _CURRENT.get()
    if _is_open_here(run):
        return run
    runs = open_runs()
    return runs[0] if len(runs) == 1 else None


def context_run():
    """The run bound to the calling context only — no process-wide fallback."""
    run = _CURRENT.get()
    return run if _is_open_here(run) else None


def register(run):
    """Mark *run* open: bind it to this context and export it to subprocesses."""
    with _LOCK:
        if not open_runs():
            _BASELINE["pid"] = os.getpid()
            _BASELINE["env"] = {key: os.environ.get(key) for key in _ENV_KEYS}
        _OPEN_RUNS.append(run)
        run._ctx_prev = _CURRENT.get()
        _CURRENT.set(run)
        _export(run)


def unregister(run):
    """Mark *run* closed and hand the context and env back. Idempotent."""
    with _LOCK:
        if run in _OPEN_RUNS:
            _OPEN_RUNS.remove(run)
        if _CURRENT.get() is run:
            prev = getattr(run, "_ctx_prev", None)
            _CURRENT.set(prev if _is_open_here(prev) else None)
        if getattr(run, "pid", os.getpid()) != os.getpid():
            return  # a forked child closing an inherited run owns no env for it
        remaining = open_runs()
        if remaining:
            _export(remaining[-1])
        else:
            _restore_baseline()


def is_foreign_sibling(verstr):
    """Whether *verstr* is a run this process has open outside this context.

    Such an id reached ``VMN_EXPERIMENT_ID`` only because another thread's run
    exported it — it is a sibling, never an enclosing launcher.
    """
    ctx = context_run()
    return any(r.id == verstr for r in open_runs()) and (
        ctx is None or ctx.id != verstr
    )


def launcher_experiment_id():
    """``VMN_EXPERIMENT_ID`` as the process received it, before any run of ours."""
    with _LOCK:
        if _BASELINE["pid"] == os.getpid() and open_runs():
            return _BASELINE["env"].get(EXPERIMENT_ID_ENV)
        return os.environ.get(EXPERIMENT_ID_ENV)


def _export(run):
    os.environ[EXPERIMENT_ID_ENV] = run.id
    os.environ[APP_NAME_ENV] = run.app_name


def _restore_baseline():
    if _BASELINE["pid"] != os.getpid():
        return
    for key, value in _BASELINE["env"].items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _BASELINE["pid"], _BASELINE["env"] = None, {}
