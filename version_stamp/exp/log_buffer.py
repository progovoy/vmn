#!/usr/bin/env python3
"""Batch an SDK run's log entries into a few whole-line writes.

A training loop logs from its hot path, and an append per metric (a stat, an
open, a write, a close, a signature bump) capped it at a couple of thousand
calls a second. Entries queue in memory instead and reach storage as one
batch: every ``FLUSH_INTERVAL_SEC`` from a daemon thread, whenever the queue
reaches ``MAX_PENDING_ENTRIES``, and on an explicit :meth:`LogBuffer.flush` —
which the run calls on each heartbeat, at ``finish()``, on SIGTERM and at
interpreter exit — so nothing logged before the run ends is lost.

Each batch is a single write of whole lines, so a reader sees an entry
entirely or not at all. A forked child that inherited the buffer, or a write
after :meth:`LogBuffer.close`, goes straight to storage.
"""
import collections
import logging
import os
import threading

from version_stamp.exp.heartbeat import Heartbeat

_LOGGER = logging.getLogger(__name__)

FLUSH_INTERVAL_SEC = 1.0
MAX_PENDING_ENTRIES = 1000


class LogBuffer:
    """Queue entries for ``write(entries)`` and hand them over in order."""

    def __init__(self, write):
        self._write = write
        self._pid = os.getpid()
        # A deque, not a locked list: appends and pops are atomic, so a
        # SIGTERM handler that flushes from the middle of an append (the
        # main thread interrupted) never waits on a lock that thread holds.
        self._pending = collections.deque()
        # Reentrant for the same reason; keeps batches in order.
        self._write_lock = threading.RLock()
        self._start_lock = threading.Lock()
        self._closed = False
        self._flusher = None

    def append(self, entry):
        if self._closed or os.getpid() != self._pid:
            self._write([entry])
            return
        self._pending.append(entry)
        if self._flusher is None:
            self._start_flusher()
        if len(self._pending) >= MAX_PENDING_ENTRIES:
            # Eager, but never on the caller's behalf: a flaky store must not
            # turn a metric call into a raised exception. The periodic flusher
            # (_flush_quietly) already swallows failures and keeps the batch
            # queued for the next attempt; reuse it here instead of the raising
            # self.flush().
            self._flush_quietly()

    def flush(self):
        """Write what is queued. On failure the batch is kept for the next try."""
        with self._write_lock:
            batch = self._take()
            if not batch:
                return
            try:
                self._write(batch)
            except BaseException:
                self._pending.extendleft(reversed(batch))
                raise

    def _take(self):
        batch = []
        for _ in range(len(self._pending)):
            batch.append(self._pending.popleft())
        return batch

    def close(self):
        """Flush and stop batching: later entries are written at once."""
        self._closed = True
        flusher, self._flusher = self._flusher, None
        if flusher is not None:
            flusher.stop()
        self.flush()

    def _start_flusher(self):
        with self._start_lock:
            if self._flusher is not None or self._closed:
                return
            self._flusher = Heartbeat(self._flush_quietly, FLUSH_INTERVAL_SEC)
            self._flusher.start()

    def _flush_quietly(self):
        try:
            self.flush()
        except Exception:
            _LOGGER.debug("Periodic log flush failed; retrying", exc_info=True)
