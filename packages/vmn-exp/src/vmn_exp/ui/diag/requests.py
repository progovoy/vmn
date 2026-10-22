#!/usr/bin/env python3
"""The ``requests`` section: what the server is doing and has been slow at.

:class:`DiagRequestsMiddleware` (outermost, so it times auth too) gives each
HTTP request a :class:`RequestEntry`, reachable from the request's context
(:func:`current_request`, also on its worker threads: anyio copies the
context). Code may attach data to ``entry.extra``; :func:`note_worker_start`
(called where a route's sync code first runs on a pool thread) splits queue
wait from run time; :mod:`~vmn_exp.ui.diag.s3_attribution` adds the
request's S3 calls (``entry.extra["s3"]``, shown as ``s3``). :meth:`RequestTracker.add_listener` subscribers get
``(event, entry)`` for ``"start"`` and ``"finish"`` (a recorder, say).

Routes are reported by their template (``/experiments/{verstr}``), never the
query string; an unrouted request by its path.
"""
import contextvars
import threading
import time
from collections import deque

from vmn_exp.ui.diag.registry import rounded as _rounded
from vmn_exp.ui.quantile_sketch import QuantileSketch

SLOW_SEC = 1.0
SLOW_RING = 200
MAX_ROUTES = 500
OTHER_ROUTES = "(other routes)"

_CURRENT = contextvars.ContextVar("vmn_ui_diag_request", default=None)


class RequestEntry:
    __slots__ = ("method", "scope", "started", "run_started", "thread", "status",
                 "duration", "response_bytes", "extra")

    def __init__(self, scope):
        self.method = scope.get("method")
        self.scope = scope  # the router adds the matched route to it
        self.started = time.monotonic()
        self.run_started = None  # when a pool thread first ran its code
        self.thread = None
        self.status = None
        self.duration = None
        self.response_bytes = 0
        self.extra = {}

    @property
    def route(self):
        route = self.scope.get("route")
        return getattr(route, "path", None) or self.scope.get("path")

    @property
    def queue_wait(self):
        return None if self.run_started is None else self.run_started - self.started


def current_request():
    """The :class:`RequestEntry` of the request this code serves, or None."""
    return _CURRENT.get()


def _s3_calls(entry):
    table = entry.extra.get("s3")
    return table.snapshot() if table is not None else {}


def note_worker_start():
    """Mark that the current request's code runs on this (pool) thread now."""
    entry = _CURRENT.get()
    if entry is None:
        return
    entry.thread = threading.current_thread().name
    if entry.run_started is None:
        entry.run_started = time.monotonic()


class _RouteStats:
    def __init__(self):
        self.count = 0
        self.max = 0.0
        self.sketch = QuantileSketch()

    def add(self, duration):
        self.count += 1
        self.max = max(self.max, duration)
        self.sketch.add(duration)

    def summary(self):
        p50, p95 = self.sketch.quantiles([0.5, 0.95])
        return {"count": self.count, "p50_sec": _rounded(p50),
                "p95_sec": _rounded(p95), "max_sec": _rounded(self.max)}


class RequestTracker:
    def __init__(self, slow_sec=SLOW_SEC, ring=SLOW_RING):
        self.slow_sec = slow_sec
        self.since = time.time()
        self._in_flight = {}  # id(entry) -> entry
        self._slow = deque(maxlen=ring)
        self._routes = {}  # "METHOD /template" -> _RouteStats
        self._listeners = []
        self._lock = threading.Lock()  # held for dict/deque updates only

    def add_listener(self, listener):
        """Call ``listener(event, entry)`` on ``"start"`` and ``"finish"``."""
        self._listeners.append(listener)

    def remove_listener(self, listener):
        self._listeners.remove(listener)

    def started(self, scope):
        entry = RequestEntry(scope)
        with self._lock:
            self._in_flight[id(entry)] = entry
        self._notify("start", entry)
        return entry

    def finished(self, entry, status):
        entry.status = status
        entry.duration = time.monotonic() - entry.started
        key = f"{entry.method} {entry.route}"
        with self._lock:
            self._in_flight.pop(id(entry), None)
            self._route_stats(key).add(entry.duration)
            if entry.duration >= self.slow_sec:
                self._slow.append(self._completed(entry))
        self._notify("finish", entry)

    def _route_stats(self, key):
        stats = self._routes.get(key)
        if stats is None:
            # Unrouted paths (401s, 404s) are keyed by path: a scanner's
            # stop growing the table at MAX_ROUTES.
            if len(self._routes) >= MAX_ROUTES:
                key = OTHER_ROUTES
                stats = self._routes.get(key)
            if stats is None:
                stats = self._routes[key] = _RouteStats()
        return stats

    def _notify(self, event, entry):
        if not self._listeners:
            return
        for listener in list(self._listeners):
            try:
                listener(event, entry)
            except Exception:  # a listener never breaks a request
                pass

    @staticmethod
    def _completed(entry):
        return {"method": entry.method, "route": entry.route, "status": entry.status,
                "duration_sec": _rounded(entry.duration),
                "queue_wait_sec": _rounded(entry.queue_wait),
                "ended_at": round(time.time(), 3), "s3": _s3_calls(entry)}

    def section(self):
        now = time.monotonic()
        with self._lock:
            flight = list(self._in_flight.values())
            slow = list(self._slow)
            routes = {key: stats.summary() for key, stats in self._routes.items()}
        return {
            "since": round(self.since, 3),
            "slow_sec": self.slow_sec,
            "in_flight": [self._flying(e, now) for e in sorted(flight, key=lambda e: e.started)],
            "slow": slow,
            "routes": routes,
        }

    @staticmethod
    def _flying(entry, now):
        return {"method": entry.method, "route": entry.route,
                "age_sec": _rounded(now - entry.started),
                "queue_wait_sec": _rounded(entry.queue_wait), "thread": entry.thread,
                "response_bytes": entry.response_bytes, "s3": _s3_calls(entry)}


class DiagRequestsMiddleware:
    """Pure ASGI: tracks every HTTP request in *tracker*."""

    def __init__(self, app, tracker):
        self.app = app
        self.tracker = tracker

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        entry = self.tracker.started(scope)
        entry.status = 500  # unless a response starts
        token = _CURRENT.set(entry)

        async def tracked_send(message):
            if message["type"] == "http.response.start":
                entry.status = message["status"]
            elif message["type"] == "http.response.body":
                entry.response_bytes += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        finally:
            _CURRENT.reset(token)
            self.tracker.finished(entry, entry.status)
