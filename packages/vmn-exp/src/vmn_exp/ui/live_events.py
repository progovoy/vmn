#!/usr/bin/env python3
"""What an SSE stream of one app's changes says, and when (plan 23 S5).

A stream re-reads the app's index snapshot (served at once by the
background refresher) every ``COALESCE_SEC``: a new snapshot object is a
new generation, diffed against the last one the stream reported, so any
number of generations in between become one ``change`` event — at most one
a second. Rows are diffed by identity (the index reuses unchanged row and
run state objects), once per pair of snapshots whatever the number of
streams. While a run in scope is live its status moves with time alone
(``stuck``), so a ``change`` also goes out every ``LIVE_TICK_SEC``. A quiet
stream sends a ``: heartbeat`` comment every ``HEARTBEAT_SEC`` (proxies drop
idle connections) and ends after ``MAX_STREAM_SEC``; the browser's
EventSource reconnects by itself, after the ``retry`` hint.

The client treats an event as "revalidate what is on screen": the payload
only says how much moved (``rows``) and, when it is cheap, which top-level
jobs (``jobs``, left out past ``MAX_JOBS``).
"""
import asyncio
import json
import threading
import time

from vmn_exp.ui.memo import LRU

COALESCE_SEC = 1.0
HEARTBEAT_SEC = 25.0
LIVE_TICK_SEC = 10
MAX_STREAM_SEC = 600.0
MAX_STREAMS = 256
MAX_JOBS = 100
RETRY_MS = 3000
# No scope, or the Jobs view's: every change of the app counts.
TOP = (None, "top")

_DIFFS = LRU(8)  # (old id, new id) -> (old, new, changed verstrs)
_LIVE = LRU(16)  # (snapshot id, scope) -> (snapshot, live verstrs in scope)


class StreamSlots:
    """At most *limit* streams open at once."""

    def __init__(self, limit=MAX_STREAMS):
        self.limit = limit
        self.active = 0
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            if self.active >= self.limit:
                return False
            self.active += 1
            return True

    def release(self):
        with self._lock:
            self.active -= 1


def _changed(old, new):
    """Verstrs whose row or run state moved between *old* and *new*, plus
    the rows that left."""
    moved = [
        row["verstr"] for row in new.rows
        if old.row(row["verstr"]) is not row
        or old.run_states.get(row["verstr"]) is not new.run_states.get(row["verstr"])
    ]
    return moved + [row["verstr"] for row in old.rows if new.row(row["verstr"]) is None]


def _changed_memo(old, new):
    return _DIFFS.get(
        (id(old), id(new)),
        lambda: (old, new, _changed(old, new)),
        valid=lambda hit: hit[0] is old and hit[1] is new,
    )[2]


def _lineage(verstr, *snapshots):
    """*verstr*, its parent, ... up to its top-level ancestor, by the edges
    of the first of *snapshots* that knows each run."""

    def parent(v):
        return next((s.edges[v] for s in snapshots if v in s.edges), None)

    chain = [verstr]
    p = parent(verstr)
    while p is not None and p not in chain and any(p in s.edges for s in snapshots):
        chain.append(p)
        p = parent(p)
    return chain


def _payload(verstrs, *snapshots):
    lineages = [_lineage(v, *snapshots) for v in verstrs]
    change = {"rows": len(verstrs)}
    jobs = sorted({chain[-1] for chain in lineages})
    if len(jobs) <= MAX_JOBS:
        change["jobs"] = jobs
    return change


def _in_scope(verstrs, scope, *snapshots):
    if scope in TOP:
        return list(verstrs)
    return [v for v in verstrs if scope in _lineage(v, *snapshots)]


def snapshot_change(old, new, scope=None):
    """``{rows, jobs?}`` of what moved from *old* to *new* within *scope*
    (a run's subtree, or the whole app); None when nothing in a run's
    subtree did."""
    rows = _in_scope(_changed_memo(old, new), scope, new, old)
    if not rows and scope not in TOP:
        return None
    return _payload(rows, new, old)


def _is_live(run_state):
    return bool(run_state) and run_state.get("exit_code") is None


def live_change(snapshot, scope=None):
    """``{rows, jobs?}`` of the live runs in *scope*; None without any."""
    live = _LIVE.per_snapshot(snapshot, lambda: _in_scope(
        [v for v, state in snapshot.run_states.items() if _is_live(state)], scope, snapshot,
    ), key=(scope,))
    return _payload(live, snapshot) if live else None


def _token(snapshot, tick):
    return f"{snapshot.generation}.{tick}"


def _event(kind, data):
    return f"event: {kind}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def event_stream(read, scope=None, clock=time.monotonic, sleep=asyncio.sleep,
                       max_sec=None):
    """The stream's chunks; *read* is an async callable answering the app's
    current snapshot."""
    max_sec = MAX_STREAM_SEC if max_sec is None else max_sec
    start = sent = clock()
    tick = int(start // LIVE_TICK_SEC)
    last = await read()
    yield f"retry: {RETRY_MS}\n" + _event("hello", {"generation": _token(last, tick)})
    while True:
        await sleep(COALESCE_SEC)
        now = clock()
        if now - start >= max_sec:
            return
        snap = await read()
        change = None
        if snap is not last:
            change = snapshot_change(last, snap, scope)
            last = snap
        now_tick = int(now // LIVE_TICK_SEC)
        if change is None and now_tick != tick:
            change = live_change(snap, scope)
        tick = now_tick
        if change is not None:
            yield _event("change", {"generation": _token(snap, tick), "changed": change})
            sent = now
        elif now - sent >= HEARTBEAT_SEC:
            yield ": heartbeat\n\n"
            sent = now
