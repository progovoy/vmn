#!/usr/bin/env python3
"""One process-wide budget of workers for concurrent object-store reads.

Every fan-out (``parallel_map``, a run's segment reads, a ``.vmx``'s chunk
prefetch) runs on its caller's thread plus the workers the budget lends it,
up to its own limit; with none spare it runs in its caller alone, so a
fan-out nested in another never waits for one. Each worker holds at most one
connection, so all fan-outs together hold at most the threads starting them
plus :data:`SHARED_WORKERS` — within the S3 client's pool
(``s3_base.MAX_POOL_CONNECTIONS``), which a fan-out each taking its own
limit's worth overflowed ("Connection pool is full").
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from vmn_exp.storage.thread_context import in_caller_context

# Half the S3 client's 320 pooled connections; the other half is for the
# threads that start fan-outs (the index's loaders, the ui's request pools).
SHARED_WORKERS = 160
_SLOTS = threading.Semaphore(SHARED_WORKERS)


def _borrow(wanted):
    slots, lent = _SLOTS, 0
    while lent < wanted and slots.acquire(blocking=False):
        lent += 1
    return slots, lent


def fan_out(fn, items, limit, name):
    """``[fn(item)]`` in order, at most *limit* at a time, on threads named
    *name* the shared budget lends (the caller's own counts as one)."""
    items = list(items)
    if len(items) < 2 or limit < 2:
        return [fn(item) for item in items]
    slots, lent = _borrow(min(limit, len(items)) - 1)
    try:
        if not lent:
            return [fn(item) for item in items]
        with ThreadPoolExecutor(max_workers=lent + 1, thread_name_prefix=name) as pool:
            return list(pool.map(in_caller_context(fn), items))
    finally:
        for _ in range(lent):
            slots.release()
