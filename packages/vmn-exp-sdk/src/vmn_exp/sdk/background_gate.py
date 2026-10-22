#!/usr/bin/env python3
"""Pause a run's background threads: ``run.pause_background()`` and fork safety.

Every storage call a run makes off the caller's thread — the heartbeat's
chores, the periodic log flush, the remote log sync, output and media
uploads — passes through the run's :class:`BackgroundGate`. Pausing it waits
for the calls in flight and holds the threads before their next call until
resumed, so nothing of the run holds a connection-pool, logging or SDK lock
while the process forks (see :mod:`vmn_exp.sdk.fork_safety`).
"""
import contextlib
import functools
import threading


class BackgroundGate:
    """Counts the background calls in flight; holds new ones while paused."""

    def __init__(self):
        self._reset()

    def _reset(self):
        self._cond = threading.Condition()
        self._paused = 0
        self._busy = {}  # thread ident -> nesting depth
        self._released = False

    def wrap(self, fn):
        """*fn* as a background call: waits while paused, counts while running."""

        @functools.wraps(fn)
        def gated(*args, **kwargs):
            with self._call(wait=True):
                return fn(*args, **kwargs)

        return gated

    def attempt(self, fn):
        """Run *fn* as a background call now, unless paused. True if it ran."""
        with self._call(wait=False) as admitted:
            if admitted:
                fn()
            return admitted

    @contextlib.contextmanager
    def _call(self, wait):
        ident = threading.get_ident()
        with self._cond:
            # A thread already inside a call finishes it: the pause waits for it.
            admitted = ident in self._busy or not self._held()
            if not admitted and wait:
                admitted = self._cond.wait_for(lambda: not self._held())
            if admitted:
                self._busy[ident] = self._busy.get(ident, 0) + 1
        if not admitted:
            yield False
            return
        try:
            yield True
        finally:
            with self._cond:
                # A call a forked child inherited mid-way left no count here.
                depth = self._busy.pop(ident, 1) - 1
                if depth:
                    self._busy[ident] = depth
                self._cond.notify_all()

    def _held(self):
        return self._paused and not self._released

    def pause(self, timeout=None):
        """Hold new calls and wait up to *timeout* seconds (None: no limit) for
        the ones in flight. True once none is (the caller's own aside)."""
        me = threading.get_ident()
        with self._cond:
            self._paused += 1
            return self._cond.wait_for(
                lambda: not (self._busy.keys() - {me}), timeout
            )

    def resume(self):
        """Undo one :meth:`pause`; calls proceed once every pause is undone."""
        with self._cond:
            self._paused = max(0, self._paused - 1)
            self._cond.notify_all()

    def release(self):
        """Never hold a call again: the run is finishing and must drain."""
        with self._cond:
            self._released = True
            self._cond.notify_all()

    def after_fork_in_child(self):
        """The child has none of the parent's threads; start from a clean gate."""
        released = self._released
        self._reset()
        self._released = released


class RunBackground:
    """``Run``'s public pause API over its ``_gate``."""

    def pause_background(self, timeout=None):
        """Quiesce this run's background threads: wait up to *timeout* seconds
        (None: until done) for a heartbeat, flush or sync call in flight, and
        start no other until :meth:`resume_background`. Logging keeps working
        (entries queue in memory). Pauses nest; ``finish()`` ends them. True if
        no call was left in flight."""
        return self._gate.pause(timeout)

    def resume_background(self):
        """Undo one :meth:`pause_background`."""
        self._gate.resume()

    @contextlib.contextmanager
    def background_paused(self, timeout=None):
        """``with run.background_paused():`` — paused inside, resumed on exit;
        yields what :meth:`pause_background` returned."""
        quiesced = self.pause_background(timeout)
        try:
            yield quiesced
        finally:
            self.resume_background()
