#!/usr/bin/env python3
"""A background step's run of consecutive failures, logged so a broken store
neither floods the log (a refresh fails every second) nor goes quiet: a
WARNING with the traceback at the streak's start, again at most every
``LOG_EVERY_SEC`` with the failure count and the last error, and a WARNING
once it recovers (INFO would not reach the default stderr handler, and the
recovery closes the warnings an operator saw)."""
import threading
import time

LOG_EVERY_SEC = 600


class FailureStreak:
    def __init__(self, what, logger, clock=time.monotonic, every_sec=LOG_EVERY_SEC, subject=None):
        """*what* failed ``for`` *subject* (when given), says each message."""
        self.what = what
        self._for = "" if subject is None else f" for {subject}"
        self.failures = 0
        self.last_error = None
        self._logger = logger
        self._clock = clock
        self._every_sec = every_sec
        self._since = self._logged_at = None
        self._lock = threading.Lock()

    @property
    def failing(self):
        return self.failures > 0

    def backoff_sec(self, base_sec, cap_sec):
        """How long to wait before trying again: *base_sec* doubling per
        failure, up to *cap_sec* (a throttling store, S3 ``SlowDown``, tried
        every second only got more of the requests it was refusing)."""
        return min(base_sec * 2 ** min(self.failures - 1, 32), cap_sec)

    def failed(self, exc):
        with self._lock:
            now = self._clock()
            self.failures += 1
            self.last_error = repr(exc)
            if self.failures == 1:
                self._since = self._logged_at = now
                self._logger.warning("%s failed%s", self.what, self._for, exc_info=exc)
            elif now - self._logged_at >= self._every_sec:
                self._logged_at = now
                self._logger.warning("%s still failing%s: %d failures in %.0f min, last error: %s",
                                     self.what, self._for, self.failures, self._minutes(now),
                                     self.last_error, exc_info=exc)
            else:
                self._logger.debug("%s failed again%s", self.what, self._for, exc_info=exc)

    def succeeded(self):
        with self._lock:
            if not self.failures:
                return
            self._logger.warning("%s recovered%s after %d failures in %.0f min", self.what,
                                 self._for, self.failures, self._minutes(self._clock()))
            self.failures, self.last_error = 0, None

    def _minutes(self, now):
        return (now - self._since) / 60
