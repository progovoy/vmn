#!/usr/bin/env python3
"""A watched index's refresh state (:mod:`vmn_exp.ui.refresher`): its thread,
its failure streak and its health, read without any I/O."""
import threading

from vmn_exp.ui.failure_streak import FailureStreak


class Watch:
    """One watched index's refresh thread and what it knows of its refreshes."""

    def __init__(self, app, clock, logger):
        self.app = app
        self.touched_at = clock()
        self.thread = None
        self.wake = threading.Event()
        self.refresh_sec = None  # how long the last refresh took
        self.refreshed_at = None  # when the last refresh that succeeded started
        self.refresh_started = None  # when the refresh in progress started
        self.slow_warned = False
        self.streak = FailureStreak("Background index refresh", logger, clock, subject=app)

    @property
    def failing(self):
        return self.streak.failing

    def alive(self):
        return self.thread is not None and self.thread.is_alive()

    def health(self, now):
        return {
            "alive": self.alive(),
            "failing": self.failing,
            "failures": self.streak.failures,
            "since_refresh_sec": _since(now, self.refreshed_at),
            "refreshing_sec": _since(now, self.refresh_started),
            "last_error": self.streak.last_error,
        }


def _since(now, then):
    return None if then is None else round(now - then, 1)
