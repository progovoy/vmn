"""Values built once per process: a forked child builds its own.

What a child inherits from its parent is unsafe to use: an object-store
client's pooled keep-alive connections are the parent's too (two writers on
one TLS session corrupt it for both), and a lock a parent thread held at the
fork stays held forever. A :class:`PerProcess` value compares the pid on each
use, which is all the parent pays; the first use in another process builds a
fresh value (the parent's is kept, never closed).
"""
import os
import threading


class PerProcess:
    """``get()`` is this process's value of ``build()`` (or *value* in the
    process that made it)."""

    def __init__(self, build, value=None):
        self._build = build
        self._by_pid = {}
        self._current = (None, None)  # (pid, value): one attribute, read atomically
        if value is not None:
            self._current = (os.getpid(), value)
            self._by_pid[os.getpid()] = value

    def get(self):
        pid = os.getpid()
        current = self._current
        if current[0] == pid:
            return current[1]
        # Threads racing to build all settle on the first value stored.
        value = self._by_pid.get(pid)
        if value is None:
            value = self._by_pid.setdefault(pid, self._build())
        self._current = (pid, value)
        return value


class PerProcessLock:
    """A ``with`` lock that is a fresh one in a forked child."""

    def __init__(self, factory=threading.Lock):
        self._locks = PerProcess(factory)

    def __enter__(self):
        return self._locks.get().__enter__()

    def __exit__(self, *exc):
        return self._locks.get().__exit__(*exc)
