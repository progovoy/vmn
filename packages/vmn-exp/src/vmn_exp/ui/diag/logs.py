#!/usr/bin/env python3
"""The ``logs`` section: what went wrong recently.

:class:`LogCapture`, a handler on the root logger, keeps the last
:data:`RING` records at WARNING and above (with their exception's type and
message), per-(logger, level) counts since start, and the last
:data:`INFO_RING` INFO records of ``vmn_exp`` loggers (progress lines). It
does no I/O and never raises.
"""
import logging
import threading
import time
from collections import deque

RING = 200
INFO_RING = 50
MAX_MESSAGE = 500
MAX_COUNTS = 500
OWN_LOGGER = "vmn_exp"

_HANDLER = None
_INSTALL_LOCK = threading.Lock()


def _truncate(text, limit=MAX_MESSAGE):
    return text if len(text) <= limit else text[:limit] + "..."


def _message(record):
    try:
        return record.getMessage()
    except Exception:  # bad %-args: keep the template
        return f"{record.msg!r} % {record.args!r}"


def _entry(record):
    exc = record.exc_info[1] if record.exc_info else None
    return {
        "at": round(record.created, 3),
        "level": record.levelname,
        "logger": record.name,
        "message": _truncate(_message(record)),
        "exc_type": type(exc).__name__ if exc is not None else None,
        "exc_message": _truncate(str(exc)) if exc is not None else None,
        "thread": record.threadName,
    }


def _is_own(name):
    return name == OWN_LOGGER or name.startswith(OWN_LOGGER + ".")


class LogCapture(logging.Handler):
    def __init__(self, ring=RING, info_ring=INFO_RING):
        super().__init__(logging.INFO)
        self.since = time.time()
        self._recent = deque(maxlen=ring)
        self._info = deque(maxlen=info_ring)
        self._counts = {}  # (logger, level) -> count
        self._counts_lock = threading.Lock()  # held for a dict update only

    def handle(self, record):
        # No handler lock: emit only appends to deques and bumps a counter.
        if record.levelno >= self.level and self.filter(record):
            self.emit(record)
        return True

    def emit(self, record):
        try:
            if record.levelno >= logging.WARNING:
                self._recent.append(_entry(record))
                self._count(record)
            elif record.levelno >= logging.INFO and _is_own(record.name):
                self._info.append(_entry(record))
        except Exception:  # logging never breaks the code that logs
            pass

    def _count(self, record):
        key = (record.name, record.levelname)
        with self._counts_lock:
            if key in self._counts or len(self._counts) < MAX_COUNTS:
                self._counts[key] = self._counts.get(key, 0) + 1

    def section(self):
        with self._counts_lock:
            counts = sorted(self._counts.items(), key=lambda item: -item[1])
        return {
            "since": round(self.since, 3),
            "recent": list(self._recent),
            "counts": [{"logger": name, "level": level, "count": n}
                       for (name, level), n in counts],
            "info": list(self._info),
        }


def install_log_capture():
    """Put the process's :class:`LogCapture` on the root logger (once) and
    let ``vmn_exp`` INFO records reach it; returns the handler."""
    global _HANDLER
    with _INSTALL_LOCK:
        if _HANDLER is None:
            _HANDLER = LogCapture()
        root = logging.getLogger()
        if _HANDLER not in root.handlers:
            if not root.handlers and logging.lastResort is not None:
                # Our handler would otherwise silence the stderr fallback.
                root.addHandler(logging.lastResort)
            root.addHandler(_HANDLER)
        own = logging.getLogger(OWN_LOGGER)
        if own.getEffectiveLevel() > logging.INFO:
            own.setLevel(logging.INFO)
        return _HANDLER


def logs_section():
    if _HANDLER is None:
        return {"installed": False}
    return _HANDLER.section()
