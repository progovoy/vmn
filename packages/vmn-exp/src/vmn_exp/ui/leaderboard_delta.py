#!/usr/bin/env python3
"""What changed between two index generations, and cached answers moved along.

The index keeps an unchanged record's row and run-state objects from one
snapshot to the next (see :class:`~vmn_exp.core.index_snapshot.RowCache`),
so the rows that changed are found by identity alone (:func:`row_delta`,
C-speed maps). A cached ordering then drops the rows that left and bisects
the new ones in (:func:`moved`) — from the generation it was last served in:
:class:`DeltaLog` composes the moves of the generations since.
"""
from collections import OrderedDict
from itertools import compress
from operator import is_not, ne, or_

from vmn_exp.core.traced_lock import TracedLock
from vmn_exp.ui.leaderboard_live import bisect_key

# A delta above this share of the rows is cheaper to rebuild from scratch.
MAX_DELTA_SHARE = 0.1
# Generations an order can be moved on across (about a minute of refreshes).
DELTA_GENERATIONS = 64
# Leading rows compared to tell one index's generations apart from another's.
_LINEAGE_ROWS = 8


def same_index(a, b):
    """Whether snapshots *a* and *b* are generations of one index: they
    share leading rows by identity (another workspace's same-named app never does)."""
    return any(x is y for x, y in zip(a.rows[:_LINEAGE_ROWS], b.rows[:_LINEAGE_ROWS]))


def delta_limit(rows):
    return int(len(rows) * MAX_DELTA_SHARE)


def changed_slots(new, old, limit):
    """Storage indexes whose row in *new* is not *old*'s row object there
    (slots past *old*'s end included); None once more than *limit*."""
    slots = list(compress(range(len(new)), map(is_not, new, old)))
    slots.extend(range(len(old), len(new)))
    return None if len(slots) > limit else slots


def left_rows(new, old, slots):
    """The rows of *old* that *slots* (from :func:`changed_slots`) replaced."""
    return [old[i] for i in slots if i < len(old)] + list(old[len(new):])


def _restated(old, new, verstrs):
    """Indexes into *verstrs* whose run state (or its store time) changed."""
    states, seen = new.run_states, new.run_state_observed_at
    was, was_seen = old.run_states, old.run_state_observed_at
    changed = map(
        or_,
        map(is_not, map(states.get, verstrs), map(was.get, verstrs)),
        map(ne, map(seen.get, verstrs), map(was_seen.get, verstrs)),
    )
    return compress(range(len(verstrs)), changed)


def row_delta(prev, snapshot):
    """``(storage indexes to re-derive, verstrs that left)`` or None."""
    old = prev.snapshot
    if len(snapshot.edges) != len(snapshot.rows) or len(prev.position) != len(old.rows):
        return None  # a verstr repeats
    limit = delta_limit(snapshot.rows)
    slots = changed_slots(snapshot.rows, old.rows, limit)
    if slots is None:
        return None
    fresh = set(slots).union(_restated(old, snapshot, list(snapshot.edges)))
    if len(fresh) > limit:
        return None
    gone = {row["verstr"] for row in left_rows(snapshot.rows, old.rows, slots)}
    fresh.update(i for i in prev.patch.live if i < len(snapshot.rows))
    return sorted(fresh), gone - snapshot.edges.keys()


def _static_row(base, verstr, changed):
    i = base.position.get(verstr)
    return None if i is None or i in changed else base.rows[i]


def static_moves(prev, base, candidates, exempt=()):
    """``(left, joined, settled)``: rows that left *prev*'s static set, rows
    that joined *base*'s, and the moved rows outside the delta limit: those
    of *joined* that were among *prev*'s changed rows (a live run that went
    stuck or finished, its ancestors), re-derived anyway like
    :func:`row_delta`'s live rows, and both copies of an *exempt* row (one
    the caller re-derived and bounded itself)."""
    was, now = set(prev.patch.changed), set(base.patch.changed)
    candidates = set(candidates)
    candidates.update(prev.rows[i]["verstr"] for i in was)
    candidates.update(base.rows[i]["verstr"] for i in now)
    left, joined, settled = [], [], []
    for verstr in candidates:
        old, new = _static_row(prev, verstr, was), _static_row(base, verstr, now)
        if old is not new:
            left.extend([old] if old is not None else [])
            joined.extend([new] if new is not None else [])
            settled.extend([new] if new is not None and old is None
                           and prev.position.get(verstr) in was else [])
            if verstr in exempt:
                settled.extend(row for row in (old, new) if row is not None)
    return left, joined, settled


def splice(rows, drop, old_key, add, new_key):
    """*rows* (sorted by *old_key*) without the *drop* rows, with the *add*
    rows placed by *new_key* — both keys agree on every row kept. None when
    a dropped row is not where its key says (the caller rebuilds)."""
    cuts = []
    for row in drop:
        at = bisect_key(rows, old_key(row), old_key)
        if at == len(rows) or rows[at] is not row:
            return None
        cuts.append((at, 1, row))
    for row in sorted(add, key=new_key):
        cuts.append((bisect_key(rows, new_key(row), old_key), 0, row))
    # Inserts before a drop at the same index; inserts keep their order.
    cuts.sort(key=lambda cut: cut[:2])
    out, cursor = [], 0
    for at, dropped, row in cuts:
        out.extend(rows[cursor:at])
        if dropped:
            cursor = at + 1
        else:
            out.append(row)
            cursor = at
    out.extend(rows[cursor:])
    return out


def moved(rows, drop, add, key):
    """*rows* (sorted by *key*) without the *drop* rows — found by identity,
    so *key* may have changed for the rows kept as long as it keeps their
    order — with the *add* rows bisected in. None when a drop row is missing."""
    ids = {id(row) for row in drop}
    kept = [row for row in rows if id(row) not in ids] if ids else rows
    if len(rows) - len(kept) != len(ids):
        return None
    return splice(kept, [], key, add, key)


class DeltaLog:
    """The static-set moves of recent generations: ``{token: (previous
    token, left, joined, settled)}`` for every base derived from another
    (see :func:`static_moves`). A move always points back to an older
    token, so a chain only counts down and every walk ends."""

    def __init__(self, size=DELTA_GENERATIONS):
        self._moves = OrderedDict()
        self._up_moved = set()  # tokens whose move changed what an up field reads
        self._size = size
        self._lock = TracedLock("leaderboard deltas")

    def add(self, base):
        """Record *base*'s move; a base derived from a newer one (an evicted
        base rebuilt for a held snapshot) forgets its token's move instead."""
        with self._lock:
            if base.delta[0] >= base.token:
                self._moves.pop(base.token, None)
                return
            self._moves[base.token] = base.delta
            if getattr(base, "up_moved", False):
                self._up_moved.add(base.token)
            while len(self._moves) > self._size:
                self._up_moved.discard(self._moves.popitem(last=False)[0])

    def since(self, token, base, reads_up=False):
        """``(left, joined)`` from generation *token* to *base*, composed;
        None when a generation between is unknown (built from scratch, or
        too old), the moves add up to more than a rebuild costs (rows
        that joined only by leaving the changed rows, and exempt ones,
        do not count) or, for
        an order that *reads_up* fields, one of them changed an ancestor's
        (see :mod:`~vmn_exp.ui.leaderboard_up`)."""
        with self._lock:
            moves = dict(self._moves)
            up_moved = set(self._up_moved) if reads_up else ()
        chain = _chain(moves, token, base.token)
        if chain is None:
            return None
        if up_moved and up_moved & {base.token, *(step[0] for step in chain[:-1])}:
            return None
        left, joined, settled = [], {}, set()
        for _, gone, came, came_settled in reversed(chain):
            for row in gone:
                if joined.pop(id(row), None) is None:
                    left.append(row)
            joined.update((id(row), row) for row in came)
            settled.update(map(id, came_settled))
        counted = sum(id(row) not in settled for row in left)
        if counted + len(joined.keys() - settled) > delta_limit(base.rows):
            return None
        return left, list(joined.values())


def _chain(moves, token, at):
    """The *moves* from *at* back to *token*, newest first; None when the
    chain breaks (it counts down, see :meth:`DeltaLog.add`, so it ends)."""
    chain = []
    while at != token:
        step = moves.get(at)
        if step is None:
            return None
        chain.append(step)
        at = step[0]
    return chain
