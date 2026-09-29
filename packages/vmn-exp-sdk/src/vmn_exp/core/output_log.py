#!/usr/bin/env python3
"""A run's console output, kept as the size-capped ``output.log`` artifact.

Bytes in, bytes out: nothing is decoded, so no output can make capture fail,
and non-UTF-8 bytes are stored exactly as written. Past the cap the first and
the last half of it are kept around an omission marker — the start holds the
config a job printed, the end holds the traceback it died with.
"""
import os
import tempfile
import threading

from vmn_exp.core.writer import compute_artifact_info, create_log_entry, save_artifact

OUTPUT_LOG_NAME = "output.log"
OUTPUT_CAP_ENV = "VMN_EXP_OUTPUT_CAP_MB"
DEFAULT_OUTPUT_CAP_MB = 10
_READ_CHUNK = 64 * 1024


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
        self._lock = threading.Lock()

    @property
    def dirty(self):
        return self._dirty

    def write(self, data):
        with self._lock:
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

    def _render(self):
        if not self._omitted:
            return bytes(self._head + self._tail)
        marker = f"\n[vmn: {self._omitted} bytes of output omitted]\n".encode()
        return bytes(self._head) + marker + bytes(self._tail)


class OutputArtifact:
    """An :class:`OutputLog` stored as a run's ``output.log`` artifact."""

    def __init__(self, storage, app_name, verstr, cap_bytes):
        self._storage = storage
        self._app_name = app_name
        self._verstr = verstr
        self._log = OutputLog(cap_bytes)
        # One upload at a time: a periodic one racing the final one could
        # leave the older content last.
        self._upload_lock = threading.Lock()

    def write(self, data):
        self._log.write(data)

    def upload(self):
        """Store the log if it changed since the last upload; True if it did."""
        with self._upload_lock:
            if not self._log.dirty:
                return False
            data = self._log.take()
            with tempfile.TemporaryDirectory(prefix="vmn-output-") as tmp:
                path = os.path.join(tmp, OUTPUT_LOG_NAME)
                with open(path, "wb") as f:
                    f.write(data)
                save_artifact(
                    self._storage, self._app_name, self._verstr, path, OUTPUT_LOG_NAME
                )
            return True

    def artifact_entry(self):
        """The ``artifact`` log entry of the log as it stands now."""
        with tempfile.TemporaryDirectory(prefix="vmn-output-") as tmp:
            path = os.path.join(tmp, OUTPUT_LOG_NAME)
            with open(path, "wb") as f:
                f.write(self._log.render())
            return create_log_entry("artifact", **compute_artifact_info(path))


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
