#!/usr/bin/env python3
"""What the background threads do: ``with activity("journal tick", key=ws):``
records per ``(name, key)`` its runs, the ones running now (thread, since),
the last and longest durations, the last error and the last success, for the
diagnostic dump (:func:`background_section`). An error is recorded and
raised on. Entries are one per ``(name, key)``, so bounded by the keys used
(apps, workspaces); reading them takes no lock.
"""
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from time import monotonic

_ENTRIES = {}  # (name, key) -> _Entry


class _Entry:
    __slots__ = ("runs", "running", "last_sec", "max_sec", "last_ok", "last_error")

    def __init__(self):
        self.runs = 0
        self.running = {}  # token -> (thread name, monotonic since)
        self.last_sec = self.max_sec = None
        self.last_ok = None  # monotonic
        self.last_error = None  # (repr, wall time, monotonic)


@contextmanager
def activity(name, key=None):
    entry = _ENTRIES.setdefault((name, key), _Entry())
    token, started = object(), monotonic()
    entry.running[token] = (threading.current_thread().name, started)
    try:
        yield
    except BaseException as exc:
        entry.last_error = (repr(exc), time.time(), monotonic())
        raise
    else:
        entry.last_ok = monotonic()
    finally:
        took = monotonic() - started
        entry.running.pop(token, None)
        entry.runs += 1
        entry.last_sec = took
        entry.max_sec = took if entry.max_sec is None else max(entry.max_sec, took)


def _rounded(value):
    return None if value is None else round(value, 4)


def _ago(now, then):
    return None if then is None else _rounded(now - then)


def _error(error, now):
    if error is None:
        return None
    text, wall, then = error
    at = datetime.fromtimestamp(wall, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return {"error": text, "at": at, "ago_sec": _ago(now, then)}


def _report(name, key, entry, now):
    running = sorted(entry.running.values(), key=lambda r: r[1])
    return {
        "name": name, "key": key, "runs": entry.runs,
        "running": [{"thread": thread, "running_sec": _ago(now, since)}
                    for thread, since in running],
        "last_sec": _rounded(entry.last_sec), "max_sec": _rounded(entry.max_sec),
        "last_ok_ago_sec": _ago(now, entry.last_ok),
        "last_error": _error(entry.last_error, now),
    }


def background_section():
    """``{"activities": [...]}``: the running ones first (longest running
    first), then the rest by name and key."""
    now = monotonic()
    found = [_report(name, key, entry, now) for (name, key), entry in list(_ENTRIES.items())]

    def order(a):
        longest = max((r["running_sec"] for r in a["running"]), default=None)
        return (longest is None, -(longest or 0), a["name"], str(a["key"]))

    return {"activities": sorted(found, key=order)}
