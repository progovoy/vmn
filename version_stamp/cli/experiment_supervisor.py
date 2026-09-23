#!/usr/bin/env python3
"""The pieces ``vmn exp run`` supervises a child with.

Each one exists so that a failure which is not the child's cannot end
supervision early: a metrics line that does not decode, a storage write that
raises, a remote sync that hangs, a SIGTERM from a scheduler. Ending early
orphans the child and leaves the run claiming ``running`` until it reads
``stuck``.
"""

import os
import signal
import sys
import threading
import time

from version_stamp.core.best_effort import BestEffort
from version_stamp.core.logging import VMN_LOGGER

# Signals a scheduler, a terminal or an operator uses to stop a job.
FORWARDED_SIGNALS = ("SIGTERM", "SIGINT", "SIGHUP")
# A terminal delivers these to its whole foreground process group, so a child
# sharing that group already has the signal.
_GROUP_DELIVERED = ("SIGINT", "SIGHUP")


def shell_exit_code(returncode):
    """Popen's ``-N`` for "killed by signal N" as a shell reports it: ``128 + N``."""
    return 128 - returncode if returncode < 0 else returncode


def signal_name(signum):
    try:
        return signal.Signals(signum).name
    except ValueError:
        return f"SIG{signum}"


class MetricsTailer:
    """Incrementally consume complete lines appended to the metrics file.

    The offset counts *bytes*, and lines are split on the newline byte before
    decoding: UTF-8 never uses that byte inside a multibyte sequence, so every
    complete line decodes on its own, and a character split across two polls is
    simply part of the trailing partial line. Undecodable bytes are replaced,
    never raised.
    """

    def __init__(self, path, parse_line):
        self._path = path
        self._parse_line = parse_line
        self._offset = 0

    def poll(self):
        try:
            with open(self._path, "rb") as f:
                f.seek(self._offset)
                chunk = f.read()
        except OSError:
            return []

        end = chunk.rfind(b"\n")
        if end < 0:
            return []  # no complete line yet
        self._offset += end + 1

        records = []
        for raw in chunk[:end].split(b"\n"):
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            parsed = self._parse_line(line)
            if parsed:
                records.append(parsed)
        return records


def supervision_guard():
    """The guard every supervision step runs under: warn once, then debug."""
    return BestEffort(
        VMN_LOGGER,
        lambda what, exc: f"Experiment run: {what} failed ({exc}); supervision continues",
    )


class BackgroundSync:
    """Remote log syncs off the supervise loop, at most one in flight.

    A sync uploads the log; on a slow link that takes longer than a heartbeat
    interval, and doing it inline starved the heartbeat until the run read
    ``stuck``.
    """

    def __init__(self, sync):
        self._sync = sync
        self._thread = None

    def request(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = self._start()

    def final(self, timeout):
        """One last sync, waiting at most *timeout* seconds for everything."""
        deadline = time.monotonic() + timeout
        if self._thread is not None:
            self._thread.join(max(0.0, deadline - time.monotonic()))
            if self._thread.is_alive():
                VMN_LOGGER.warning("Experiment run: final sync skipped, a sync hangs")
                return
        thread = self._start()
        thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            VMN_LOGGER.warning(f"Experiment run: final sync timed out after {timeout}s")

    def _start(self):
        thread = threading.Thread(target=self._sync, name="vmn-exp-sync", daemon=True)
        thread.start()
        return thread


def _delivered_by_terminal(signum, proc):
    """Whether a terminal already sent *signum* to the child's process group."""
    if signal_name(signum) not in _GROUP_DELIVERED:
        return False
    try:
        return os.tcgetpgrp(sys.stdin.fileno()) == os.getpgid(proc.pid)
    except (AttributeError, OSError, ValueError):
        return False


class SignalForwarder:
    """Relay termination signals to the child while a run is supervised.

    The first signal is forwarded — unless a terminal already delivered it to
    the child's foreground group, which would make it arrive twice — and starts
    a grace period, after which a child that is still alive is killed. A second
    signal kills it at once. Handlers are only installable from the main thread;
    elsewhere the forwarder is inert.
    """

    def __init__(self, grace_sec):
        self.received = None
        self._grace_sec = grace_sec
        self._kill_at = None
        self._proc = None
        self._previous = {}

    def install(self):
        for name in FORWARDED_SIGNALS:
            signum = getattr(signal, name, None)
            if signum is None:
                continue
            try:
                self._previous[signum] = signal.signal(signum, self._handle)
            except (OSError, ValueError):
                pass  # not the main thread

    def restore(self):
        for signum, handler in self._previous.items():
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                pass
        self._previous.clear()

    def attach(self, proc):
        self._proc = proc
        if self.received is not None:
            self._forward(getattr(signal, self.received))

    def enforce_grace(self):
        """Kill a child that outlived the grace period of a forwarded signal."""
        if self._kill_at is not None and time.monotonic() >= self._kill_at:
            self._kill()

    def _handle(self, signum, _frame):
        if self.received is not None:
            self._kill()
            return
        self.received = signal_name(signum)
        self._kill_at = time.monotonic() + self._grace_sec
        self._forward(signum)

    def _forward(self, signum):
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        if _delivered_by_terminal(signum, proc):
            return
        try:
            proc.send_signal(signum)
        except OSError:
            pass

    def _kill(self):
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
