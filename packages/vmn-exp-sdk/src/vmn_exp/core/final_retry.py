#!/usr/bin/env python3
"""Retry a run's last upload until it lands or the caller gives up on it.

A run's final state and final log sync are its last word: a failure there,
unlike a heartbeat's, is not repaired by the next attempt, because there is
none. So each is retried with growing delays until it lands or the caller's
deadline abandons it, and the last error is kept for the caller to report.
"""
import itertools

DEFAULT_DELAYS = (0.5, 1, 2, 5)


class FinalRetry:
    """Call ``attempt(item)`` until it returns or ``wait(delay)`` returns True.

    *wait* blocks for *delay* seconds and reports whether the retries were
    abandoned meanwhile (``threading.Event().wait`` in production). Past the
    last of *delays* the last one repeats."""

    def __init__(self, attempt, wait, delays=DEFAULT_DELAYS):
        self._attempt = attempt
        self._wait = wait
        self._delays = delays
        self.landed = False
        self.error = None

    def run(self, item):
        for retry in itertools.count():
            try:
                self._attempt(item)
            except Exception as exc:
                self.error = exc
            else:
                self.landed = True
                return
            if self._wait(self._delays[min(retry, len(self._delays) - 1)]):
                return
