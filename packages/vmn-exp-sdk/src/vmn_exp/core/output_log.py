#!/usr/bin/env python3
"""A run's console output, kept as the size-capped ``outputs/output.log``.

Bytes in, bytes out: nothing is decoded, so no output can make capture fail,
and non-UTF-8 bytes are stored exactly as written. Past the cap the first and
the last half of it are kept around an omission marker — the start holds the
config a job printed, the end holds the traceback it died with.
"""
import hashlib
import os
import tempfile
import threading
import time

from vmn_exp.core.writer import create_log_entry, save_artifact
from vmn_exp.storage.files import OUTPUTS_DIR

OUTPUT_LOG_NAME = "output.log"
# Its record-relative path: a vmn output, never a user artifact.
OUTPUT_LOG_PATH = f"{OUTPUTS_DIR}/{OUTPUT_LOG_NAME}"
OUTPUT_CAP_ENV = "VMN_EXP_OUTPUT_CAP_MB"
DEFAULT_OUTPUT_CAP_MB = 10
_READ_CHUNK = 64 * 1024
# Each periodic upload re-sends the whole object: space them so a run spends
# at most this much upload bandwidth on it (a full 10 MB log: every ~160s).
UPLOAD_BYTES_PER_SEC = 64 * 1024


def output_cap_bytes(cap_mb):
    """*cap_mb* (a flag's value), else ``$VMN_EXP_OUTPUT_CAP_MB``, else 10 MB."""
    for value in (cap_mb, os.environ.get(OUTPUT_CAP_ENV)):
        try:
            if value is not None and float(value) > 0:
                return int(float(value) * 1024 * 1024)
        except ValueError:
            pass
    return DEFAULT_OUTPUT_CAP_MB * 1024 * 1024


class OutputLog:
    """The first and last ``cap_bytes / 2`` of everything written; thread-safe."""

    def __init__(self, cap_bytes):
        self._head_cap = cap_bytes // 2
        self._tail_cap = cap_bytes - self._head_cap
        self._head = bytearray()
        self._tail = bytearray()
        self._omitted = 0
        self._dirty = False
        self._closed = False
        self._lock = threading.Lock()

    @property
    def dirty(self):
        return self._dirty

    def write(self, data):
        with self._lock:
            if self._closed:
                return
            room = self._head_cap - len(self._head)
            if room > 0:
                self._head += data[:room]
                data = data[room:]
            self._tail += data
            excess = len(self._tail) - self._tail_cap
            if excess > 0:
                del self._tail[:excess]
                self._omitted += excess
            self._dirty = True

    def render(self):
        with self._lock:
            return self._render()

    def take(self):
        """The rendered log, marking it clean."""
        with self._lock:
            self._dirty = False
            return self._render()

    def close(self):
        """The final rendered log; later writes are dropped."""
        with self._lock:
            self._closed = True
            self._dirty = False
            return self._render()

    def _render(self):
        if not self._omitted:
            return b"".join((self._head, self._tail))
        marker = f"\n[vmn: {self._omitted} bytes of output omitted]\n".encode()
        return b"".join((self._head, marker, self._tail))


def _artifact_entry(data):
    return create_log_entry(
        "artifact",
        path=OUTPUT_LOG_PATH,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


class OutputArtifact:
    """An :class:`OutputLog` stored as a run's ``outputs/output.log``.

    Periodic uploads are throttled to :data:`UPLOAD_BYTES_PER_SEC`; after
    :meth:`seal` the final log uploads on the next call, unthrottled.
    """

    def __init__(self, storage, app_name, verstr, cap_bytes, clock=time.monotonic):
        self._storage = storage
        self._app_name = app_name
        self._verstr = verstr
        self._log = OutputLog(cap_bytes)
        self._clock = clock
        self._next_upload_at = None
        self._sealed = None
        # One upload at a time: a periodic one racing the final one could
        # leave the older content last.
        self._upload_lock = threading.Lock()

    def write(self, data):
        self._log.write(data)

    def seal(self):
        """End the log; returns the ``artifact`` log entry of what it holds."""
        self._sealed = self._log.close()
        return _artifact_entry(self._sealed)

    def upload(self):
        """Store the log if it changed and an upload is due; True if it did."""
        with self._upload_lock:
            data = self._take_due()
            if data is None:
                return False
            self._store(data)
            self._next_upload_at = self._clock() + len(data) / UPLOAD_BYTES_PER_SEC
            return True

    def artifact_entry(self):
        """The ``artifact`` log entry of the log as it stands now."""
        return _artifact_entry(self._log.render())

    def _take_due(self):
        if self._sealed is not None:
            data, self._sealed = self._sealed, None
            return data
        if not self._log.dirty:
            return None
        if self._next_upload_at is not None and self._clock() < self._next_upload_at:
            return None
        return self._log.take()

    def _store(self, data):
        with tempfile.TemporaryDirectory(prefix="vmn-output-") as tmp:
            path = os.path.join(tmp, OUTPUT_LOG_NAME)
            with open(path, "wb") as f:
                f.write(data)
            save_artifact(
                self._storage, self._app_name, self._verstr, path, OUTPUT_LOG_PATH
            )


def pump(src_fd, dest_fd, sink):
    """Copy *src_fd* to *dest_fd* and *sink(bytes)* until EOF. Never raises.

    A destination or sink that fails is skipped, never a reason to stop
    reading: a writer blocked on a full pipe nobody drains would hang.
    """
    while True:
        try:
            data = os.read(src_fd, _READ_CHUNK)
        except OSError:
            return
        if not data:
            return
        _write_all(dest_fd, data)
        try:
            sink(data)
        except Exception:
            pass


def _write_all(fd, data):
    view = memoryview(data)
    try:
        while view:
            view = view[os.write(fd, view):]
    except OSError:
        pass
