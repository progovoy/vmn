#!/usr/bin/env python3
"""Process-wide S3 request statistics for the ``vmn-exp ui`` diagnostic dump.

:func:`instrument` registers botocore ``before-call``/``after-call``/
``after-call-error`` hooks on every client :mod:`vmn_exp.storage.s3_base`
builds (S3 and S3-compatible stores; the gs/az backends use their own SDKs
and are not covered). Per operation: count, errors by code, retries (the
response's ``RetryAttempts``, so a call's latency includes its retries),
in-flight now, a fixed-bucket latency histogram and bytes read; per
operation and key kind (:func:`~vmn_exp.storage.s3_kinds.classify`) count,
errors and latency; the last :data:`FAILURES_SHOWN` failed calls with their
keys. Hooks never
raise into the request path; :func:`s3_stats` is the dump section.
:func:`add_listener` callbacks get an :data:`S3Call` after each call, on the
calling thread (a recorder can read the request's contextvars); no listener
costs one tuple truthiness check.
"""
import bisect
import collections
import itertools
import threading
import time
import weakref

from vmn_exp.storage.s3_kinds import classify

# Upper bounds (ms) of the latency buckets; one more bucket holds the rest.
BOUNDS_MS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000,
             10000, 30000, 60000)
# Oldest in-flight requests a dump lists.
IN_FLIGHT_SHOWN = 10
# Last failed calls a dump lists.
FAILURES_SHOWN = 50
_START = "_vmn_s3_stats"
_KEY = "_vmn_s3_key"

# One finished call, as a listener sees it (``status`` is None and ``error``
# the exception's class name when no HTTP response came back).
S3Call = collections.namedtuple(
    "S3Call", "operation key duration_ms status error retries bytes_read")

_lock = threading.Lock()
_ops = {}
_kinds = {}  # "<operation> <kind>" -> _KindStats
_failures = collections.deque(maxlen=FAILURES_SHOWN)  # (t, op, key, error, status)
_in_flight = {}  # id(request context) -> (t0, operation, path, ClientStats)
_clients = weakref.WeakKeyDictionary()  # client -> ClientStats
_serials = itertools.count(1)
_created = 0
_pool_sizes = set()  # every client's max_pool_connections
_listeners = ()  # replaced, never mutated: hooks read it without the lock


class LatencyHistogram:
    """Fixed buckets over :data:`BOUNDS_MS`: memory never grows with calls."""

    def __init__(self):
        self.buckets = [0] * (len(BOUNDS_MS) + 1)
        self.max = 0.0

    def add(self, ms):
        self.buckets[bisect.bisect_left(BOUNDS_MS, ms)] += 1
        self.max = max(self.max, ms)

    def quantile(self, q):
        total = sum(self.buckets)
        if not total:
            return 0.0
        seen = 0
        for i, n in enumerate(self.buckets):
            seen += n
            if seen >= q * total:
                bound = BOUNDS_MS[i] if i < len(BOUNDS_MS) else self.max
                return min(bound, self.max)
        return self.max

    def summary(self):
        return {"p50": round(self.quantile(0.5), 3),
                "p95": round(self.quantile(0.95), 3), "max": round(self.max, 3)}


class _OpStats:
    def __init__(self):
        self.count = 0
        self.errors = {}
        self.retries = 0
        self.in_flight = 0
        self.bytes_read = 0
        self.latency = LatencyHistogram()

    def as_dict(self):
        return {"count": self.count, "errors": dict(self.errors),
                "retries": self.retries, "in_flight": self.in_flight,
                "bytes_read": self.bytes_read, "latency_ms": self.latency.summary()}


class _KindStats:
    def __init__(self):
        self.count = 0
        self.errors = {}
        self.latency = LatencyHistogram()

    def as_dict(self):
        return {"count": self.count, "errors": dict(self.errors),
                "latency_ms": self.latency.summary()}


def _op(name):
    stats = _ops.get(name)
    if stats is None:
        stats = _ops[name] = _OpStats()
    return stats


class ClientStats:
    """One client's hooks and in-flight count (against its connection pool)."""

    def __init__(self, max_pool_connections):
        self.serial = next(_serials)
        self.max_pool_connections = max_pool_connections
        self.in_flight = 0
        self.peak_in_flight = 0

    def before_parameter_build(self, params=None, context=None, **_):
        try:
            context[_KEY] = str(params.get("Key") or params.get("Prefix") or "")[:200]
        except Exception:
            pass

    def before_call(self, model=None, context=None, **_):
        try:
            op = model.name
            t0 = time.monotonic()
            context[_START] = (t0, op)
            with _lock:
                _op(op).in_flight += 1
                self.in_flight += 1
                self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
                _in_flight[id(context)] = (t0, op, context.get(_KEY, ""), self)
        except Exception:
            pass

    def after_call(self, context=None, parsed=None, http_response=None, **_):
        try:
            parsed = parsed or {}
            status = getattr(http_response, "status_code", None)
            error = (parsed.get("Error") or {}).get("Code")
            if error is None and (status or 0) >= 300:
                error = str(status)
            meta = parsed.get("ResponseMetadata") or {}
            nbytes = parsed.get("ContentLength") or 0
            self._finish(context, status, error, meta.get("RetryAttempts", 0),
                         nbytes if isinstance(nbytes, int) else 0)
        except Exception:
            pass

    def after_call_error(self, context=None, exception=None, **_):
        try:
            self._finish(context, None, type(exception).__name__, 0, 0)
        except Exception:
            pass

    def _finish(self, context, status, error, retries, nbytes):
        start = context.pop(_START, None)
        if start is None:
            return
        t0, op = start
        now = time.monotonic()
        ms = (now - t0) * 1000
        key = context.get(_KEY, "")
        by_kind = f"{op} {classify(op, key)}"
        with _lock:
            _in_flight.pop(id(context), None)
            self.in_flight -= 1
            stats = _op(op)
            stats.in_flight -= 1
            stats.count += 1
            stats.retries += retries
            stats.bytes_read += nbytes
            stats.latency.add(ms)
            kind = _kinds.get(by_kind)
            if kind is None:
                kind = _kinds[by_kind] = _KindStats()
            kind.count += 1
            kind.latency.add(ms)
            if error:
                stats.errors[error] = stats.errors.get(error, 0) + 1
                kind.errors[error] = kind.errors.get(error, 0) + 1
                _failures.append((now, op, key, error, status))
        if _listeners:
            _notify(S3Call(op, key, ms, status, error, retries, nbytes))

    def as_dict(self):
        return {"client": self.serial, "max_pool_connections": self.max_pool_connections,
                "in_flight": self.in_flight, "peak_in_flight": self.peak_in_flight}


def add_listener(fn):
    """Call ``fn(S3Call)`` after each S3 call, on the calling thread."""
    global _listeners
    with _lock:
        _listeners = _listeners + (fn,)


def remove_listener(fn):
    global _listeners
    with _lock:
        _listeners = tuple(f for f in _listeners if f is not fn)


def _notify(call):
    for fn in _listeners:
        try:
            fn(call)
        except Exception:
            pass


def instrument(client):
    """Count *client*'s S3 calls; returns *client*."""
    global _created
    try:
        hooks = ClientStats(client.meta.config.max_pool_connections)
        events = client.meta.events
        events.register("before-parameter-build.s3", hooks.before_parameter_build)
        events.register("before-call.s3", hooks.before_call)
        events.register("after-call.s3", hooks.after_call)
        events.register("after-call-error.s3", hooks.after_call_error)
        with _lock:
            _clients[client] = hooks
            _pool_sizes.add(hooks.max_pool_connections)
            _created += 1
    except Exception:
        pass
    return client


def s3_stats():
    """The dump section: per-operation and per-kind stats, pools, oldest
    in-flight calls, the last failed calls (newest first)."""
    now = time.monotonic()
    with _lock:
        operations = {name: op.as_dict() for name, op in sorted(_ops.items())}
        by_kind = {name: k.as_dict() for name, k in sorted(_kinds.items())}
        failures = list(_failures)
        clients = [c.as_dict() for c in _clients.values()]
        oldest = sorted(_in_flight.values(), key=lambda r: r[0])[:IN_FLIGHT_SHOWN]
        created = _created
        pool_sizes = sorted(_pool_sizes)
    clients.sort(key=lambda c: -c["in_flight"])
    return {
        "operations": operations,
        "by_kind": by_kind,
        "clients_created": created,
        "clients_alive": len(clients),
        "max_pool_connections": pool_sizes,
        "clients": clients,
        "in_flight": [{"operation": op, "key": key, "client": c.serial,
                       "age_ms": round((now - t0) * 1000, 1)}
                      for t0, op, key, c in oldest],
        "recent_failures": [{"operation": op, "key": key, "error": error, "status": status,
                             "age_sec": round(now - t, 3)}
                            for t, op, key, error, status in reversed(failures)],
    }
