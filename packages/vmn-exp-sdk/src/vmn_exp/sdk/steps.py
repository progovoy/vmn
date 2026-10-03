#!/usr/bin/env python3
"""A run's auto-incrementing metrics step: one counter with a high-water mark.

A ``log_metrics`` call without ``step=`` records the counter's value and
advances it; an explicit step is recorded as given and only ever raises the
counter (a lower one is kept, never dropped: forks and rewinds re-log old
steps).
"""
import threading

from vmn_exp.core.rewind import drop_rewound
from vmn_exp.core.series_reader import SeriesReader


class StepCounter:
    """The next step to record. Thread-safe."""

    def __init__(self, first=0):
        self._next = first
        self._lock = threading.Lock()

    @property
    def next(self):
        return self._next

    def take(self, step=None, commit=True):
        """The step to record *step* (None: the counter's) at; a committed
        step is consumed, an uncommitted one is shared with the next call."""
        with self._lock:
            if step is None:
                step = self._next
            self._next = max(self._next, int(step) + (1 if commit else 0))
            return step


def first_step(storage, app_name, verstr, start_step, resumed):
    """Where a run's counter starts: a fork/rewind's *start_step*, else one
    past a resumed run's highest visible metrics step, else 0."""
    if start_step is not None:
        return start_step
    if not resumed:
        return 0
    return resume_next_step(storage.load_merged_log(app_name, verstr))


def resume_next_step(log):
    """One past the highest step of *log*'s visible metric points (0: none)."""
    reader = SeriesReader.from_entries(drop_rewound(log))
    steps = [s for key in reader.keys() for s in reader.points(key).steps if s is not None]
    return int(max(steps)) + 1 if steps else 0
