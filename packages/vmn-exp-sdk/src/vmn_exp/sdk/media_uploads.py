#!/usr/bin/env python3
"""A run's logged media files, stored off the training thread.

``log_image``/``log_table`` encode their file on the caller's thread (that is
the work the caller asked for), hash it, log its entry and hand the file
here: storing it may be an S3 PUT, which must not stall a training loop.
Unlike the latest-wins :class:`~vmn_exp.core.background.Coalescing` jobs,
every file is stored, once, in the order logged. The run's finalization
waits for the queue.

So the entry (an output of the run) may precede its file: a reader can see it
for as long as the upload takes. A file that could not be stored — the save
raised, or it was still queued when the final wait ran out — is reported to
``on_failed(name, exc)``, which retracts the output; it is never left
claimed forever.
"""
import logging
import queue
import shutil
import tempfile
import threading

_LOGGER = logging.getLogger("vmn_exp.sdk")
_STOP = object()


def staging_dir():
    """A fresh directory for one file; the uploader removes it once stored."""
    return tempfile.mkdtemp(prefix="vmn-media-")


class MediaUploads:
    """Calls ``save(path, name)`` for each submitted file on one worker thread."""

    def __init__(self, save, on_failed=None, name="vmn-media-upload"):
        self._save = save
        self._on_failed = on_failed
        self._name = name
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread = None
        self._closed = False

    def submit(self, staged_dir, path, name):
        """Store *path* (inside *staged_dir*, removed afterwards) as *name*."""
        with self._lock:
            if not self._closed:
                if self._thread is None:
                    self._thread = threading.Thread(
                        target=self._loop, name=self._name, daemon=True
                    )
                    self._thread.start()
                self._queue.put((staged_dir, path, name))
                return
        self._store(staged_dir, path, name)  # logged after close: store inline

    def close(self, timeout):
        """Store what is queued, then stop. False if that took over *timeout*:
        the files not started by then are given up (reported failed)."""
        with self._lock:
            self._closed = True
            thread = self._thread
            if thread is not None:
                self._queue.put(_STOP)
        if thread is None:
            return True
        thread.join(timeout)
        if not thread.is_alive():
            return True
        self._abandon_queued()
        return False

    def _abandon_queued(self):
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                break
            if job is not _STOP:
                staged_dir, _, name = job
                shutil.rmtree(staged_dir, ignore_errors=True)
                self._failed(name, TimeoutError("not stored before the run finished"))
        self._queue.put(_STOP)  # the file in flight still ends the worker

    def _loop(self):
        while True:
            job = self._queue.get()
            if job is _STOP:
                return
            self._store(*job)

    def _store(self, staged_dir, path, name):
        try:
            self._save(path, name)
        except Exception as exc:
            self._failed(name, exc)
        finally:
            shutil.rmtree(staged_dir, ignore_errors=True)

    def _failed(self, name, exc):
        _LOGGER.warning(f"vmn: could not store media file {name}: {exc}")
        if self._on_failed is None:
            return
        try:
            self._on_failed(name, exc)
        except Exception:
            _LOGGER.debug("Could not retract media file %s", name, exc_info=True)
