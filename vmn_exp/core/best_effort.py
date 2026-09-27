#!/usr/bin/env python3
"""Running the chores a run's liveness depends on, without ever raising.

Both run recorders — ``vmn exp run`` supervising a child and the SDK's
in-process ``Run`` — have steps that must not end the run when they fail: a
heartbeat write, a remote sync, a final state. A failure there is reported,
never thrown at the workload.
"""
import threading


class BestEffort:
    """Call a step; on failure report it and return None instead of raising.

    *describe(what, exc)* words the report. With *warn_first* the first failure
    of each step is a warning — the user should learn their heartbeat or sync
    is failing — and repeats go to debug, so a flapping backend cannot flood
    the output. Without it every failure is debug-only.
    """

    def __init__(self, logger, describe, warn_first=True):
        self._logger = logger
        self._describe = describe
        self._warn_first = warn_first
        self._warned = set()
        self._lock = threading.Lock()

    def __call__(self, what, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if self._first_failure(what):
                self._logger.warning(self._describe(what, exc))
            self._logger.debug(f"{what} failed", exc_info=True)
            return None

    def _first_failure(self, what):
        if not self._warn_first:
            return False
        with self._lock:
            first = what not in self._warned
            self._warned.add(what)
        return first


def quiet(logger):
    """A :class:`BestEffort` that only ever logs at debug."""
    return BestEffort(logger, describe=None, warn_first=False)

