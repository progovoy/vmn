#!/usr/bin/env python3
"""The ``latency`` section: is the process itself starved?

Two probes measure how late a sleep wakes up, over the last
:data:`WINDOW_SEC`: a task on the server's event loop (a blocked loop shows
here) and a daemon thread (under the GIL, a pegged interpreter shows here).
Each keeps a bounded deque of ``(monotonic, wall, lag)`` samples.
"""
import asyncio
import math
import threading
import time
from collections import deque

WINDOW_SEC = 300.0
LOOP_INTERVAL_SEC = 0.25
THREAD_INTERVAL_SEC = 0.05


def _ms(value):
    return None if value is None else round(value * 1000, 3)


def _quantile(ordered, q):
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


class LagStats:
    def __init__(self, window_sec=WINDOW_SEC, interval_sec=THREAD_INTERVAL_SEC):
        self.window_sec = window_sec
        self.interval_sec = interval_sec
        # A lagging probe samples less often, so this bounds the window too.
        self._samples = deque(maxlen=int(window_sec / interval_sec) + 1)

    def add(self, lag):
        self._samples.append((time.monotonic(), time.time(), max(0.0, lag)))

    def summary(self):
        horizon = time.monotonic() - self.window_sec
        samples = [s for s in list(self._samples) if s[0] >= horizon]
        if not samples:
            return {"interval_sec": self.interval_sec, "samples": 0, "p50_ms": None,
                    "p95_ms": None, "max_ms": None, "last_ms": None, "worst_at": None}
        ordered = sorted(lag for _, _, lag in samples)
        worst = max(samples, key=lambda s: s[2])
        return {
            "interval_sec": self.interval_sec,
            "samples": len(samples),
            "p50_ms": _ms(_quantile(ordered, 0.5)),
            "p95_ms": _ms(_quantile(ordered, 0.95)),
            "max_ms": _ms(worst[2]),
            "last_ms": _ms(samples[-1][2]),
            "worst_at": round(worst[1], 3),
        }


LOOP_STATS = LagStats(interval_sec=LOOP_INTERVAL_SEC)
THREAD_STATS = LagStats(interval_sec=THREAD_INTERVAL_SEC)
_THREAD = None
_THREAD_LOCK = threading.Lock()
_LOOP_TASK = None


def thread_probe_step(stats, interval, sleep=time.sleep):
    started = time.monotonic()
    sleep(interval)
    stats.add(time.monotonic() - started - interval)


def _thread_probe(stats, interval):
    while True:
        thread_probe_step(stats, interval)


def start_thread_probe():
    """The process's thread probe (started on the first call)."""
    global _THREAD
    with _THREAD_LOCK:
        if _THREAD is None:
            _THREAD = threading.Thread(target=_thread_probe, daemon=True,
                                       args=(THREAD_STATS, THREAD_INTERVAL_SEC),
                                       name="vmn-ui-diag-lag")
            _THREAD.start()
        return _THREAD


async def loop_probe(stats, interval):
    loop = asyncio.get_running_loop()
    while True:
        started = loop.time()
        await asyncio.sleep(interval)
        stats.add(loop.time() - started - interval)


def _loop_probe_live():
    return (_LOOP_TASK is not None and not _LOOP_TASK.done()
            and not _LOOP_TASK.get_loop().is_closed())


def install_loop_probe(app):
    """Run the loop probe on *app*'s event loop from startup to shutdown
    (one at a time per process)."""

    async def start():
        global _LOOP_TASK
        if not _loop_probe_live():
            _LOOP_TASK = asyncio.ensure_future(loop_probe(LOOP_STATS, LOOP_INTERVAL_SEC))

    async def stop():
        if _LOOP_TASK is not None and _LOOP_TASK.get_loop() is asyncio.get_running_loop():
            _LOOP_TASK.cancel()

    app.router.on_startup.append(start)
    app.router.on_shutdown.append(stop)


def latency_section():
    return {"event_loop": LOOP_STATS.summary(), "thread": THREAD_STATS.summary()}
