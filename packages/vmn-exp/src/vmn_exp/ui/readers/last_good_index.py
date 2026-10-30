#!/usr/bin/env python3
"""The succeeded runs of each command, by storage position, per index snapshot.

What a failed or stuck run's ``last_good`` (plan 20 K4) bisects instead of
walking the app's earlier rows. Built once per snapshot and shared by every
request against it; a new generation's is moved along from the app's last
one by its delta (rows and run states compared by identity, see
:mod:`vmn_exp.ui.leaderboard_delta`), rebuilt when the delta is large. A
``succeeded`` status never depends on the clock, so only a changed row or run
state moves a run in or out.
"""
import threading
from bisect import bisect_left, insort
from itertools import compress
from operator import is_not

from vmn_exp.core.index_snapshot import schema_less
from vmn_exp.core.status import SUCCEEDED, derive_status
from vmn_exp.ui.leaderboard_delta import changed_slots, delta_limit, same_index
from vmn_exp.ui.memo import LRU

PER_APP = 2  # the indexes kept per app: its newest snapshots'
_NOT = object()  # a slot whose run is no succeeded one


def _frozen(value):
    """*value* hashable, equal where it was equal: lists as tuples, dicts as
    tagged item tuples (so a dict never equals a list of its pairs)."""
    if isinstance(value, list):
        return tuple(_frozen(v) for v in value)
    if isinstance(value, dict):
        return (dict, tuple(sorted((k, _frozen(v)) for k, v in value.items())))
    return value


def _command_key(state):
    """*state*'s command, hashable (an argv list as a tuple)."""
    return _frozen((state or {}).get("command"))


def _succeeded_command(row, run_states):
    """*row*'s run's command when it succeeded unarchived, else :data:`_NOT`."""
    state = run_states.get(row["verstr"])
    if row.get("archived") or derive_status(state) != SUCCEEDED:
        return _NOT
    return _command_key(state)


class SucceededByCommand:
    """``{command: [storage position of a succeeded run]}`` of one snapshot's
    *rows* and *run_states*; the lists are shared with the next generation's
    until it changes them."""

    def __init__(self, snapshot, by_command):
        self.rows, self.run_states, self.by_command = snapshot.rows, snapshot.run_states, by_command

    @classmethod
    def build(cls, snapshot):
        by_command = {}
        for i, row in enumerate(snapshot.rows):
            command = _succeeded_command(row, snapshot.run_states)
            if command is not _NOT:
                by_command.setdefault(command, []).append(i)
        return cls(snapshot, by_command)

    def latest_before(self, command, position):
        """The row of the latest succeeded run of *command* stored before
        *position*, or None."""
        found = self.by_command.get(command, ())
        at = bisect_left(found, position)
        return self.rows[found[at - 1]] if at else None


def _touched(prev, snapshot):
    """Storage positions whose row or run state changed since *prev*, or
    None when the delta is large or rows left."""
    rows, old = snapshot.rows, prev.rows
    limit = delta_limit(rows)
    if len(rows) < len(old) or len(snapshot.edges) != len(rows):
        return None
    slots = changed_slots(rows, old, limit)
    if slots is None:
        return None
    states, was = snapshot.run_states, prev.run_states
    if states is not was:
        verstrs = list(snapshot.edges)
        slots = set(slots).union(compress(
            range(len(verstrs)), map(is_not, map(states.get, verstrs), map(was.get, verstrs))))
    return None if len(slots) > limit else slots


def _moved(prev, snapshot):
    slots = _touched(prev, snapshot)
    if slots is None:
        return None
    by_command, copied = dict(prev.by_command), set()

    def positions(command):
        if command not in copied:
            copied.add(command)
            by_command[command] = list(by_command.get(command, ()))
        return by_command[command]

    for i in slots:
        was = _succeeded_command(prev.rows[i], prev.run_states) if i < len(prev.rows) else _NOT
        if was is not _NOT:
            positions(was).remove(i)
        now = _succeeded_command(snapshot.rows[i], snapshot.run_states)
        if now is not _NOT:
            insort(positions(now), i)
    return SucceededByCommand(snapshot, by_command)


class _Indexes:
    """A :class:`SucceededByCommand` per snapshot, each moved on from the
    app's latest; the last :data:`PER_APP` of each app kept."""

    def __init__(self):
        self._indexes = {}  # app -> LRU of its snapshots' indexes
        self._latest = {}  # app -> (the snapshot's leading rows, its index) built last
        self._lock = threading.Lock()

    def get(self, snapshot):
        with self._lock:
            indexes = self._indexes.get(snapshot.app_name)
            if indexes is None:
                indexes = self._indexes[snapshot.app_name] = LRU(PER_APP)
        return indexes.per_snapshot(snapshot, lambda: self._built(snapshot))

    def _built(self, snapshot):
        with self._lock:
            prev = self._latest.get(snapshot.app_name)
        index = (prev and same_index(prev, snapshot) and _moved(prev, snapshot)) \
            or SucceededByCommand.build(snapshot)
        with self._lock:
            self._latest[snapshot.app_name] = index
        return index


_INDEXES = _Indexes()


def _position(rows, row):
    pos = (row.get("idx") or 0) - 1
    if 0 <= pos < len(rows) and rows[pos]["verstr"] == row["verstr"]:
        return pos
    return next((i for i, r in enumerate(rows) if r["verstr"] == row["verstr"]), 0)


def last_good_row(snapshot, verstr):
    """The row of the latest earlier unarchived succeeded run of *verstr*'s
    command, or None (also for a run *snapshot* lacks)."""
    snapshot = schema_less(snapshot)
    row = snapshot.row(verstr)
    if row is None:
        return None
    index = _INDEXES.get(snapshot)
    command = _command_key(snapshot.run_states.get(verstr))
    return index.latest_before(command, _position(index.rows, row))
