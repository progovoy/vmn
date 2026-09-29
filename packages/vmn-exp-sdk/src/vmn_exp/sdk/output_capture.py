#!/usr/bin/env python3
"""``start_run(capture_output=True)``: tee this process's fd 1 and 2 into ``output.log``.

At the file-descriptor level, not ``sys.stdout``: output from C extensions,
``os.write`` and subprocesses is kept too. Each fd is pointed at a pipe whose
reader thread copies every chunk to the original fd (so the terminal still
gets it) and into the run's output log. ``stop()`` points the fds back.

Opt-in: redirecting a host process's descriptors is invasive — the process
then sees pipes, not a TTY, and an interactive debugger or a notebook kernel
may not expect that.
"""
import os
import sys
import threading

from vmn_exp.core.background import Coalescing
from vmn_exp.core.output_log import OutputArtifact, output_cap_bytes, pump

_FDS = (1, 2)
# How long stop() waits for a pipe to drain. A subprocess that inherited the
# pipe can hold it open; it is not waited for.
_DRAIN_TIMEOUT_SEC = 2


def _flush_python_streams():
    # Only from the main thread: a SIGTERM finalizer runs on a worker thread
    # while the main thread may hold a stream's lock mid-write.
    if threading.current_thread() is not threading.main_thread():
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass


class FdCapture:
    """Tee fds 1 and 2 into *sink(bytes)* between ``start()`` and ``stop()``."""

    def __init__(self, sink):
        self._sink = sink
        self._redirected = []  # (fd, saved original, pipe read end, thread)

    def start(self):
        _flush_python_streams()
        for fd in _FDS:
            saved = os.dup(fd)
            read_end, write_end = os.pipe()
            os.dup2(write_end, fd)
            os.close(write_end)
            thread = threading.Thread(
                target=pump,
                args=(read_end, saved, self._sink),
                name=f"vmn-output-{fd}",
                daemon=True,
            )
            thread.start()
            self._redirected.append((fd, saved, read_end, thread))

    def stop(self):
        """Point the fds back and drain what was written before. Idempotent."""
        _flush_python_streams()
        redirected, self._redirected = self._redirected, []
        for fd, saved, _, _ in redirected:
            os.dup2(saved, fd)  # closes this fd's hold on the pipe: EOF follows
        for _, saved, read_end, thread in redirected:
            thread.join(_DRAIN_TIMEOUT_SEC)
            if not thread.is_alive():  # still pumping into *saved* otherwise
                os.close(read_end)
                os.close(saved)


class RunOutput:
    """A run's captured console: the fd tee plus its off-thread uploads."""

    def __init__(self, storage, app_name, verstr):
        self._artifact = OutputArtifact(
            storage, app_name, verstr, output_cap_bytes(None)
        )
        self._capture = FdCapture(self._artifact.write)
        # Off the heartbeat thread: a slow upload must not delay a beat.
        self._uploader = Coalescing(
            lambda _: self._artifact.upload(), "vmn-exp-output-upload"
        )

    def start(self):
        self._capture.start()

    def request_upload(self):
        self._uploader.submit()

    def stop(self):
        """Stop capturing and queue the last upload; returns its log entry."""
        self._capture.stop()
        self._uploader.submit()
        return self._artifact.artifact_entry()

    def close(self, timeout):
        return self._uploader.close(timeout)
