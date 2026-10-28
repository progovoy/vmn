#!/usr/bin/env python3
"""``vmn-exp ui``'s log lines: each starts with a UTC timestamp, its level
and its logger, so an operator can line a warning up with a diagnostic dump
or a metrics graph.

vmn's logger keeps its own stdout/stderr handlers, now timestamped; every
other logger (vmn_exp's modules, uvicorn's, the libraries') reaches stderr
through one root handler from WARNING up, which leaves vmn's records to
vmn's handlers (the stdlib fallback printed them a second time, bare). A
thread's uncaught exception is logged too, instead of the stdlib's print.
"""
import logging
import sys
import threading
import time

from version_stamp.api import VMN_LOGGER

FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOGGER = logging.getLogger("vmn_exp.ui")


class UtcFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802 (logging's name)
        return utc_stamp(record.created)


def utc_stamp(created=None):
    """``2026-10-28T13:47:25.830Z`` for *created* (default: now)."""
    created = time.time() if created is None else created
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(created)) + \
        f".{int(created * 1000) % 1000:03d}Z"


class _Stderr(logging.StreamHandler):
    """Writes to whatever ``sys.stderr`` is at the time (like the stdlib's
    fallback handler), skipping vmn's records, which vmn's handlers print."""

    def __init__(self):
        super().__init__()
        self.setLevel(logging.WARNING)
        self.addFilter(lambda record: not _is_vmn(record.name))

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, value):
        pass


def _is_vmn(name):
    vmn = VMN_LOGGER.name
    return name == vmn or name.startswith(vmn + ".")


def install():
    """Timestamp every line the server logs (idempotent)."""
    formatter = UtcFormatter(FORMAT)
    for handler in VMN_LOGGER.handlers:
        handler.setFormatter(formatter)
    root = logging.getLogger()
    if logging.lastResort in root.handlers:  # the diag log capture's fallback
        root.removeHandler(logging.lastResort)
    stderr = next((h for h in root.handlers if isinstance(h, _Stderr)), None) or _Stderr()
    stderr.setFormatter(formatter)
    if stderr not in root.handlers:
        root.addHandler(stderr)
    threading.excepthook = _log_thread_exception


def _log_thread_exception(args):
    if issubclass(args.exc_type, SystemExit):
        return
    name = args.thread.name if args.thread is not None else "?"
    _LOGGER.error("Uncaught exception in thread %s", name,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
