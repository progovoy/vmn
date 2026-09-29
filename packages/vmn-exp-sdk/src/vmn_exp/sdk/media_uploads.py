#!/usr/bin/env python3
"""A run's logged media files, stored off the training thread.

``log_image``/``log_table`` encode their file on the caller's thread (that is
the work the caller asked for) and hand it here: storing it may be an S3 PUT,
which must not stall a training loop. Unlike the latest-wins
:class:`~vmn_exp.core.background.Coalescing` jobs, every file is stored,
once, in the order logged. The run's finalization waits for the queue.
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

    def __init__(self, save, name="vmn-media-upload"):
        self._save = save
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
        """Store what is queued, then stop. False if that took over *timeout*."""
        with self._lock:
            self._closed = True
            thread = self._thread
            if thread is not None:
                self._queue.put(_STOP)
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

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
            _LOGGER.warning(f"vmn: could not store media file {name}: {exc}")
        finally:
            shutil.rmtree(staged_dir, ignore_errors=True)
