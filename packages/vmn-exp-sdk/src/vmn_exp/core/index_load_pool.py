"""The thread pool a remote index's in-process load reads records in.

Each record costs a few GETs and then CPU: its YAML parsed, its log folded.
On a GIL build one thread runs at a time whatever the pool's size, and the
rest wait on the network, so the load keeps all its threads. On a
free-threaded build they run at once, and every collection stops the world
and waits for each of them: threads past the cores only lengthen the pauses
(plan 28 appendix A row 6), so there the pool is capped at the cores this
process may use.

A bulk load reads its records a chunk at a time; :class:`LoadPool` keeps one
pool across its chunks (started on first use, ended by :meth:`close`).
"""
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor


def cores():
    """The CPUs this process may use (its affinity where the OS says)."""
    count_of = getattr(os, "process_cpu_count", None) or os.cpu_count
    return count_of() or 1


def free_threaded():
    is_gil_enabled = getattr(sys, "_is_gil_enabled", None)
    return is_gil_enabled is not None and not is_gil_enabled()


def load_threads(most):
    """At most *most* threads, and on a free-threaded build no more than the
    cores."""
    return max(1, min(most, cores())) if free_threaded() else most


class LoadPool:
    """A pool of :func:`load_threads` threads named *prefix*, kept until closed."""

    def __init__(self, most, prefix):
        self._most, self._prefix = most, prefix
        self._pool = None
        self._lock = threading.Lock()

    def map(self, fn, items):
        return list(self._started().map(fn, items))

    def _started(self):
        with self._lock:
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=load_threads(self._most),
                                                thread_name_prefix=self._prefix)
            return self._pool

    def close(self):
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False)
