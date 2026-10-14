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
from itertools import compress
from operator import is_not

from vmn_exp.core.tree import ancestors
from vmn_exp.ui.leaderboard_delta import changed_slots, left_rows
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

_DIFFS = LRU(2)  # (old id, new id) -> (old, new, changed verstrs)
_LIVE = LRU(2)  # (snapshot id,) -> (snapshot, live verstrs)


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
    the rows that left: the slots whose row object changed (C-speed, see
    :func:`~vmn_exp.ui.leaderboard_delta.changed_slots`), checked by verstr
    so rows a removal shifted are not counted."""
    slots = changed_slots(new.rows, old.rows, len(new.rows))
    moved = {
        row["verstr"] for row in (new.rows[i] for i in slots)
        if old.row(row["verstr"]) is not row
    }
    verstrs, states, was = list(new.edges), new.run_states, old.run_states
    moved.update(compress(verstrs, map(is_not, map(states.get, verstrs), map(was.get, verstrs))))
    left = [row["verstr"] for row in left_rows(new.rows, old.rows, slots)
            if new.row(row["verstr"]) is None]
    return list(moved) + left


def _changed_memo(old, new):
    return _DIFFS.get(
        (id(old), id(new)),
        lambda: (old, new, _changed(old, new)),
        valid=lambda hit: hit[0] is old and hit[1] is new,
    )[2]


class _Edges:
    """The parent links of the first of *snapshots* that knows each run;
    a parent no snapshot knows ends a chain."""

    def __init__(self, snapshots):
        self._snapshots = snapshots

    def get(self, verstr):
        parent = next((s.edges[verstr] for s in self._snapshots if verstr in s.edges), None)
        return parent if any(parent in s.edges for s in self._snapshots) else None


def _lineage(verstr, *snapshots):
    """*verstr*, its parent, ... up to its top-level ancestor."""
    return [verstr] + ancestors(verstr, _Edges(snapshots))


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
    live = _LIVE.per_snapshot(snapshot, lambda: [
        v for v, state in snapshot.run_states.items() if _is_live(state)])
    live = _in_scope(live, scope, snapshot)
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
