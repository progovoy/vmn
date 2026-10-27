#!/usr/bin/env python3
"""Records a refresh could not read, set aside instead of failing it.

One record that fails to read (a bug, an object a writer is replacing, a
malformed file) used to fail the whole refresh, every retry the same: the
index stopped updating, and the sweep's reset restarted its listing behind
serving. Now the refresh goes on without it; the record keeps what the index
had (a new one stays out), its first failure is logged with its key and
traceback, and it is read afresh once its retry is due: *base_sec* after the
first failure, doubling per failure up to :data:`MAX_RETRY_SEC`.

A failure of the store itself (:func:`store_failed`: a reset connection, a
timeout, a refused or throttled request) still fails the refresh: it is not
the record's, and the refresher retries the refresh, keeping what it read.
"""
import logging
import threading

MAX_RETRY_SEC = 600.0
_STORE_CLIENTS = ("botocore", "boto3", "urllib3", "google", "azure")

_LOGGER = logging.getLogger("vmn_exp.core.index")


def store_failed(exc):
    """Whether *exc* is the store's failure, not the record's."""
    return isinstance(exc, OSError) or type(exc).__module__.split(".")[0] in _STORE_CLIENTS


class Unreadable:
    def __init__(self, app_name, clock):
        self._app, self._clock = app_name, clock
        self._failed = {}  # key -> (failed at, failures)
        self._lock = threading.Lock()

    def __contains__(self, key):
        return key in self._failed

    def __len__(self):
        return len(self._failed)

    def failed(self, key, exc):
        with self._lock:
            failures = self._failed.get(key, (0, 0))[1] + 1
            self._failed[key] = (self._clock(), failures)
        if failures == 1:
            _LOGGER.warning("Index of %s: could not read %s; set aside, retried later",
                            self._app, key, exc_info=exc)
        else:
            _LOGGER.debug("Index of %s: %s still unreadable (%d failures)",
                          self._app, key, failures, exc_info=exc)

    def read(self, key):
        with self._lock:
            self._failed.pop(key, None)

    def due(self, base_sec):
        """The keys whose retry is due now."""
        now = self._clock()
        with self._lock:
            return [key for key, (at, failures) in self._failed.items()
                    if now - at >= min(base_sec * 2 ** (failures - 1), MAX_RETRY_SEC)]
