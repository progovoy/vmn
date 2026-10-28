#!/usr/bin/env python3
"""Caps the S3 calls in flight per key prefix, process-wide.

S3 throttles per prefix (~3,500 PUT / 5,500 GET a second), so a cold load's
or a fan-out's calls under one app draw ``SlowDown``s long before the client's
pool runs out. :func:`cap_prefixes` registers botocore hooks on a client: a
call takes a slot of its ``(bucket, prefix_of(key))`` bounded semaphore in
``before-call`` and gives it back in ``after-call``/``after-call-error``, so
the slot is held across the call's retries but not while a ``GetObject``
body is read afterwards. A thread already holding a slot of that prefix (a
call made from inside another one's hooks) takes none: nested calls never
deadlock. The cap is :data:`DEFAULT_PREFIX_CONCURRENCY`, or
``VMN_EXP_S3_PREFIX_CONCURRENCY`` (read when a prefix is first seen; 0 or
invalid = the default). :func:`prefix_cap_stats` is the diag dump's view of
in-flight calls and waits. Hooks never raise into the request path.
"""
import os
import threading
import time

from vmn_exp.storage import areas

# ~20 ms a call makes 64 slots ~3,200 calls a second: under S3's per-prefix
# rates, and a fifth of the client's pool (s3_base.MAX_POOL_CONNECTIONS).
DEFAULT_PREFIX_CONCURRENCY = 64
ENV = "VMN_EXP_S3_PREFIX_CONCURRENCY"
# Prefixes a dump lists, most waited-on first.
PREFIXES_SHOWN = 20
_AREAS = frozenset((areas.RUNS, areas.SNAPSHOTS, areas.CODE, areas.SWEEPS, areas.REGISTRY,
                    areas.REPORTS, areas.COMMENTS, areas.SETTINGS, areas.JOURNAL))
_TARGET = "_vmn_s3_cap_target"
_SLOT = "_vmn_s3_cap_slot"

_lock = threading.Lock()
_caps = {}  # (bucket, prefix) -> _PrefixCap
_held = threading.local()  # .depth: {_PrefixCap: calls of this thread in it}


def limit():
    try:
        value = int(os.environ.get(ENV, ""))
    except ValueError:
        return DEFAULT_PREFIX_CONCURRENCY
    return value if value > 0 else DEFAULT_PREFIX_CONCURRENCY


def prefix_of(key):
    """*key*'s throttling prefix: the root through the area and its scope
    (``<root>/runs/<app>``), the area for a listing of it, else the first
    segment."""
    parts = [p for p in key.split("/") if p]
    for i, part in enumerate(parts[:-1]):
        if part in _AREAS:
            return "/".join(parts[:i + 2])
    if parts and parts[-1] in _AREAS:
        return "/".join(parts)
    return parts[0] if len(parts) > 1 else ""


class _PrefixCap:
    def __init__(self, bucket, prefix, size):
        self.bucket, self.prefix, self.limit = bucket, prefix, size
        self.slots = threading.BoundedSemaphore(size)
        self.in_flight = self.peak_in_flight = self.waiting = self.waits = 0
        self.wait_ms_total = self.wait_ms_max = 0.0

    def acquire(self):
        if not self.slots.acquire(blocking=False):
            with _lock:
                self.waiting += 1
            t0 = time.monotonic()
            self.slots.acquire()
            ms = (time.monotonic() - t0) * 1000
            with _lock:
                self.waiting -= 1
                self.waits += 1
                self.wait_ms_total += ms
                self.wait_ms_max = max(self.wait_ms_max, ms)
        with _lock:
            self.in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self.in_flight)

    def release(self):
        with _lock:
            self.in_flight -= 1
        self.slots.release()

    def as_dict(self):
        return {"bucket": self.bucket, "prefix": self.prefix, "limit": self.limit,
                "in_flight": self.in_flight, "peak_in_flight": self.peak_in_flight,
                "waiting": self.waiting, "waits": self.waits,
                "wait_ms_total": round(self.wait_ms_total, 1),
                "wait_ms_max": round(self.wait_ms_max, 1)}


def _cap_of(bucket, prefix):
    with _lock:
        cap = _caps.get((bucket, prefix))
        if cap is None:
            cap = _caps[(bucket, prefix)] = _PrefixCap(bucket, prefix, limit())
        return cap


def _depths():
    depth = getattr(_held, "depth", None)
    if depth is None:
        depth = _held.depth = {}
    return depth


def _before_parameter_build(params=None, context=None, **_):
    try:
        key = str(params.get("Key") or params.get("Prefix") or "")
        context[_TARGET] = (str(params.get("Bucket") or ""), prefix_of(key))
    except Exception:
        pass


def _before_call(context=None, **_):
    try:
        cap = _cap_of(*context[_TARGET])
        depth = _depths()
        if not depth.get(cap):
            cap.acquire()
        depth[cap] = depth.get(cap, 0) + 1
        context[_SLOT] = cap
    except Exception:
        pass


def _after_call(context=None, **_):
    try:
        cap = context.pop(_SLOT, None)
        if cap is None:
            return
        depth = _depths()
        depth[cap] -= 1
        if not depth[cap]:
            del depth[cap]
            cap.release()
    except Exception:
        pass


def cap_prefixes(client):
    """Cap *client*'s calls per prefix; returns *client*."""
    try:
        events = client.meta.events
        events.register("before-parameter-build.s3", _before_parameter_build)
        events.register("before-call.s3", _before_call)
        events.register("after-call.s3", _after_call)
        events.register("after-call-error.s3", _after_call)
    except Exception:
        pass
    return client


def prefix_cap_stats():
    """The dump section: the cap and the most waited-on prefixes."""
    with _lock:
        rows = [cap.as_dict() for cap in _caps.values()]
    rows.sort(key=lambda r: (-r["waiting"], -r["waits"], -r["peak_in_flight"]))
    return {"limit": limit(), "prefixes_seen": len(rows), "prefixes": rows[:PREFIXES_SHOWN]}
