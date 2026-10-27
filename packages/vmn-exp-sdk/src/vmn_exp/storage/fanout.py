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

:data:`REQUEST_WORKERS` of them are only lent to fan-outs serving a request
(:func:`serving_request`), so a run page's reads never run one by one while
background fan-outs (an index load's folds, upkeep) hold the rest.
"""
import contextlib
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor

from vmn_exp.storage.thread_context import in_caller_context

# Half the S3 client's 320 pooled connections; the other half is for the
# threads that start fan-outs (the index's loaders, the ui's request pools).
SHARED_WORKERS = 160
REQUEST_WORKERS = 32
_SLOTS = threading.Semaphore(SHARED_WORKERS - REQUEST_WORKERS)
_REQUEST_SLOTS = threading.Semaphore(REQUEST_WORKERS)
_SERVING = contextvars.ContextVar("vmn_fanout_serving_request", default=False)


@contextlib.contextmanager
def serving_request():
    """Fan-outs started in this context (and on pool threads it is copied
    to) may borrow the workers reserved for requests."""
    token = _SERVING.set(True)
    try:
        yield
    finally:
        _SERVING.reset(token)


def _borrow(wanted):
    """``[(semaphore, n)]`` of the workers lent, at most *wanted* in all."""
    pools = (_REQUEST_SLOTS, _SLOTS) if _SERVING.get() else (_SLOTS,)
    loans = []
    for slots in pools:
        lent = 0
        while lent < wanted and slots.acquire(blocking=False):
            lent += 1
        loans.append((slots, lent))
        wanted -= lent
    return loans


def fan_out(fn, items, limit, name):
    """``[fn(item)]`` in order, at most *limit* at a time, on threads named
    *name* the shared budget lends (the caller's own counts as one)."""
    items = list(items)
    if len(items) < 2 or limit < 2:
        return [fn(item) for item in items]
    loans = _borrow(min(limit, len(items)) - 1)
    lent = sum(n for _, n in loans)
    try:
        if not lent:
            return [fn(item) for item in items]
        with ThreadPoolExecutor(max_workers=lent + 1, thread_name_prefix=name) as pool:
            return list(pool.map(in_caller_context(fn), items))
    finally:
        for slots, n in loans:
            for _ in range(n):
                slots.release()
