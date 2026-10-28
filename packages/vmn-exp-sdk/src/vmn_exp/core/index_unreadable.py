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
timeout, a refused or throttled request) sets the record aside too: failing
the refresh dropped the reads of the records around it, and on S3 a
``SlowDown`` past botocore's retries failed every refresh after it. Those are
not the record's, so they are warned about once per :data:`STORE_LOG_EVERY_SEC`
for all records, with the count set aside meanwhile; a store that cannot
list fails the refresh at its listing.

:meth:`Unreadable.summary` tells the index's freshness how many are set
aside: the refresh succeeds around them, so it is the dashboard's only sign.
"""
import logging
import threading

MAX_RETRY_SEC = 600.0
STORE_LOG_EVERY_SEC = 600.0
ERROR_CHARS = 200
_STORE_CLIENTS = ("botocore", "boto3", "urllib3", "google", "azure")

_LOGGER = logging.getLogger("vmn_exp.core.index")


class StoreRefused(OSError):
    """A store failure met in a worker process, as it crosses the pipe (a
    client's exception may not pickle)."""

    @classmethod
    def of(cls, exc):
        return cls(f"{type(exc).__name__}: {exc}")


def store_failed(exc):
    """Whether *exc* is the store's failure, not the record's."""
    return isinstance(exc, OSError) or type(exc).__module__.split(".")[0] in _STORE_CLIENTS


class Unreadable:
    def __init__(self, app_name, clock):
        self._app, self._clock = app_name, clock
        self._failed = {}  # key -> (failed at, failures, a store failure)
        self._store_errors, self._last_error = 0, None
        self._store_warned_at, self._store_failures = float("-inf"), 0
        self._lock = threading.Lock()

    def __contains__(self, key):
        return key in self._failed

    def __len__(self):
        return len(self._failed)

    def failed(self, key, exc):
        store = store_failed(exc)
        with self._lock:
            _, failures, was_store = self._failed.get(key, (0, 0, False))
            failures += 1
            self._failed[key] = (self._clock(), failures, store)
            self._store_errors += store - was_store
            self._last_error = repr(exc)[:ERROR_CHARS]
        if store:
            self._warn_store_failure(key, exc)
        elif failures == 1:
            _LOGGER.warning("Index of %s: could not read %s; set aside, retried later",
                            self._app, key, exc_info=exc)
        else:
            _LOGGER.debug("Index of %s: %s still unreadable (%d failures)",
                          self._app, key, failures, exc_info=exc)

    def _warn_store_failure(self, key, exc):
        with self._lock:
            self._store_failures += 1
            now = self._clock()
            due = now - self._store_warned_at >= STORE_LOG_EVERY_SEC
            if due:
                count, self._store_failures, self._store_warned_at = self._store_failures, 0, now
        if due:
            _LOGGER.warning("Index of %s: the store failed reading %s (%d records set aside"
                            " since the last warning, retried later): %s",
                            self._app, key, count, exc)
        else:
            _LOGGER.debug("Index of %s: the store failed reading %s", self._app, key, exc_info=exc)

    def read(self, key):
        with self._lock:
            entry = self._failed.pop(key, None)
            if entry is not None:
                self._store_errors -= entry[2]

    def forget(self, keys):
        """*keys* are gone from the store: none is unreadable any more."""
        for key in keys:
            self.read(key)

    def summary(self):
        """``{count, store_errors, last_error}`` of the records set aside
        (*store_errors*: how many failed on the store's failure, not their
        own; *last_error*: the latest failure's short repr), else None."""
        with self._lock:
            if not self._failed:
                return None
            return {"count": len(self._failed), "store_errors": self._store_errors,
                    "last_error": self._last_error}

    def due(self, base_sec):
        """The keys whose retry is due now."""
        now = self._clock()
        with self._lock:
            return [key for key, entry in self._failed.items() if _due(entry, now, base_sec)]

    def is_due(self, key, base_sec):
        """Whether set-aside *key*'s retry is due now (a listing before then
        reads nothing: a live run is listed every heartbeat)."""
        entry = self._failed.get(key)
        return entry is not None and _due(entry, self._clock(), base_sec)


def _due(entry, now, base_sec):
    at, failures, _ = entry
    return now - at >= min(base_sec * 2 ** min(failures - 1, 32), MAX_RETRY_SEC)
