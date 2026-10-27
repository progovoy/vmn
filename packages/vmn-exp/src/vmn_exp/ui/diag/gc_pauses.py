#!/usr/bin/env python3
"""The ``gc`` section: how often and for how long the cyclic collector ran.

A ``gc.callbacks`` hook times every collection (start to stop: on a
free-threaded build that is a stop-the-world scan of the whole heap, then
the garbage's finalization) and keeps totals per generation plus the last
:data:`RECENT` pauses. Always on: a few tuples per collection.

Collections never overlap (CPython runs one at a time), so the callback
writes without a lock; a reader copies, and a collection the copy races
with shows in the next dump. A lock here could deadlock: an allocation
made while a reader held it may start a collection on the same thread.
"""
import gc
import os
import sys
import time
from collections import deque

from vmn_exp.ui.diag.latency import _ms
from vmn_exp.ui.gil_hint import gil_enabled

RECENT = 32


class GcPauses:
    def __init__(self, recent=RECENT, clock=time.perf_counter, wall=time.time):
        self._clock, self._wall = clock, wall
        self._started = None  # (clock, wall) of the collection running now
        self._recent = deque(maxlen=recent)
        self._by_generation = {}  # generation -> [collections, total sec, max sec]
        self._worst = (0.0, None, None)  # (sec, wall, generation)
        self._collected = self._uncollectable = 0

    def callback(self, phase, info):
        if phase == "start":
            self._started = (self._clock(), self._wall())
            return
        if self._started is None:
            return
        started, at = self._started
        self._started = None
        self._record(self._clock() - started, at, info)

    def _record(self, sec, at, info):
        generation = info.get("generation")
        collected, uncollectable = info.get("collected", 0), info.get("uncollectable", 0)
        self._collected += collected
        self._uncollectable += uncollectable
        totals = self._by_generation.get(generation)
        if totals is None:
            totals = self._by_generation[generation] = [0, 0.0, 0.0]
        totals[0] += 1
        totals[1] += sec
        totals[2] = max(totals[2], sec)
        if sec >= self._worst[0]:
            self._worst = (sec, at, generation)
        self._recent.append((at, sec, generation, collected, uncollectable))

    def stats(self):
        by_generation = {str(g): {"collections": n, "total_ms": _ms(total), "max_ms": _ms(worst)}
                         for g, (n, total, worst) in sorted(dict(self._by_generation).items())}
        worst, worst_at, worst_generation = self._worst
        return {
            "collections": sum(g["collections"] for g in by_generation.values()),
            "total_ms": round(sum(g["total_ms"] for g in by_generation.values()), 3),
            "max_ms": _ms(worst),
            "max_at": worst_at,
            "max_generation": worst_generation,
            "collected": self._collected,
            "uncollectable": self._uncollectable,
            "by_generation": by_generation,
            "recent": [{"at": at, "ms": _ms(sec), "generation": g, "collected": c,
                        "uncollectable": u} for at, sec, g, c, u in list(self._recent)],
        }


PAUSES = GcPauses()


def install():
    """Time every collection from now on (once per process)."""
    if PAUSES.callback not in gc.callbacks:
        gc.callbacks.append(PAUSES.callback)


def allocator_info(environ=os.environ, free_threaded=None):
    """The allocator (a free-threaded build always uses mimalloc), its
    ``PYTHONMALLOC``/``MIMALLOC_*`` settings and the allocated block count."""
    free_threaded = not gil_enabled() if free_threaded is None else free_threaded
    env = {k: v for k, v in environ.items() if k == "PYTHONMALLOC" or k.startswith("MIMALLOC_")}
    name = "mimalloc" if free_threaded else (environ.get("PYTHONMALLOC") or "pymalloc")
    return {"name": name, "allocated_blocks": sys.getallocatedblocks(), "env": env}


def gc_section():
    return {
        "enabled": gc.isenabled(),
        "gil_enabled": gil_enabled(),
        "threshold": list(gc.get_threshold()),
        "freeze_count": gc.get_freeze_count(),
        **PAUSES.stats(),
        "allocator": allocator_info(),
    }
