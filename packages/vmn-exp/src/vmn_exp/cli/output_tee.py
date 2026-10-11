#!/usr/bin/env python3
"""Tee a supervised child's stdout/stderr to the terminal and ``output.log``.

The child writes to two pipes; one thread per pipe copies each chunk to the
supervisor's own fd 1 or 2 — exactly where the child would have written — and
into the run's :class:`~vmn_exp.core.output_log.OutputArtifact`. Pipes, not a
pty: a pty merges the two streams, rewrites line endings, is POSIX-only, and
makes tools paint colour codes and progress redraws into the log. The cost is
that the child sees ``isatty() == False``; ``PYTHONUNBUFFERED=1`` is set (unless
the user set it) so a Python child still streams live.
"""
import subprocess
import threading

from vmn_exp.core.background import join_all
from vmn_exp.core.output_log import OutputArtifact, OutputLog, output_cap_bytes, pump

# How long the end of a run waits for the pipes to drain. A grandchild that
# inherited them can hold them open past the child's exit; it is not waited for.
_DRAIN_TIMEOUT_SEC = 5


def output_artifact(storage, app_name, verstr, args):
    """The run's ``output.log``, or None under ``--no-capture-output``."""
    if not getattr(args, "capture_output", True):
        return None
    cap = output_cap_bytes(getattr(args, "output_cap_mb", None))
    return OutputArtifact(storage, app_name, verstr, cap)


def popen_kwargs(env):
    """The Popen stdio for a captured child, and the env it should get."""
    env.setdefault("PYTHONUNBUFFERED", "1")
    return {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "env": env}


# The end of the child's stderr kept apart from output.log, where stdout lines
# can interleave with a traceback: the run's error is parsed from it.
_STDERR_TAIL_BYTES = 64 * 1024


class OutputTee:
    """Pump a child's two pipes until they close."""

    def __init__(self, proc, sink):
        self.stderr = OutputLog(_STDERR_TAIL_BYTES)

        def stderr_sink(data):
            self.stderr.write(data)
            sink(data)

        self._threads = [
            threading.Thread(
                target=pump,
                args=(stream.fileno(), fd, stream_sink),
                name=f"vmn-exp-output-{fd}",
                daemon=True,
            )
            for stream, fd, stream_sink in ((proc.stdout, 1, sink), (proc.stderr, 2, stderr_sink))
        ]
        for thread in self._threads:
            thread.start()

    def drain(self, timeout=_DRAIN_TIMEOUT_SEC):
        join_all(self._threads, timeout)

    def stderr_text(self):
        return self.stderr.render().decode("utf-8", errors="replace")

