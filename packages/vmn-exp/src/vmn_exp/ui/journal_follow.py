#!/usr/bin/env python3
"""One change-journal reader per store workspace (plan 11 §5.2).

Each :meth:`WorkspaceJournal.tick` lists the store's journal once (whatever
the number of apps) and routes every new entry by ``(area, app)`` to the
watched index of that scope as a ``hint``; entries for scopes nobody watches
are dropped (a later watch catches up as below), and a scope that overflows
gets the names it overflowed with and a listing of its record names
(``overflowed``; an index without it reconciles). ``reports``/``comments`` entries go to the
workspace's report index (:meth:`WorkspaceJournal.feed_reports`), fed every
tick, idle ones too, so it reads no journal of its own while this one runs.
The cursor persists in the workspace's ``CacheStore`` kv, so a restart
resumes where it stopped — never further back than the journal keeps
(``retain_sec``), many partitions listed at once.

Every tick tells each watched index how far its hints reach (``journal_at``),
which it persists with its records as its journal mark. A new watch of an
index whose mark the journal still covers (``resume_journal``) replays the
journal from the mark at the next tick instead of reconciling: a restarted
server lists no record it did not hear about.

With an *election* (Postgres mode, plan 11 §4.3) only the replica leading
the workspace's journal ticks; it passes every entry to *relay* as
``<scope>|<name>`` (``NOTIFY vmn_hint``; an empty name asks to reconcile),
and every replica routes those to its own watched indexes and report index
with :meth:`WorkspaceJournal.receive`. A new leader resumes from the shared cursor.
"""
import threading
import time

from vmn_exp.core.journal_reader import JournalReader
from vmn_exp.storage.areas import COMMENTS, REPORTS, RUNS, app_key
from vmn_exp.storage.journal import JOURNAL_MAX_AGE_SEC

_CURSOR_FINGERPRINT = "journal-cursor"
# A mark this close to the journal's retention lists fully instead: hosts'
# clocks and the lifecycle rule's timing differ.
REPLAY_MARGIN_SEC = 3600
LIST_WORKERS = 16
_REPORT_AREAS = (REPORTS, COMMENTS)


class WorkspaceJournal:
    def __init__(self, list_fn, cache, scope, clock=time.time, election=None, relay=None,
                 retain_sec=JOURNAL_MAX_AGE_SEC, **reader_kw):
        self._cache, self._scope = cache, f"journal:{scope}"
        self._election, self._relay, self._leading = election, relay, False
        self._clock, self._retain_sec = clock, retain_sec
        reader_kw.setdefault("max_lookback_sec", retain_sec)
        reader_kw.setdefault("workers", LIST_WORKERS)
        self._skew_sec = reader_kw.get("skew_window_sec", 300)
        self._new_reader = lambda cursor: JournalReader.from_cursor(
            cursor, list_fn, clock, **reader_kw)
        self._reader = self._new_reader(self._saved_cursor())
        self._indexes = {}  # (area, app key) -> index
        self._replays = {}  # (area, app key) -> the journal mark to replay it from
        self._reports = None  # the workspace's ReportIndex, once it asks
        self._lock = threading.Lock()

    def use_cache(self, cache):
        """Keep the cursor in *cache* from now on (the cache was rebuilt)."""
        self._cache = cache
        self._cache.kv_put(self._scope, _CURSOR_FINGERPRINT, self._reader.cursor)

    @property
    def scope(self):
        return self._scope

    @property
    def cursor(self):
        return self._reader.cursor

    @property
    def watched(self):
        return bool(self._indexes)

    def watch(self, index, area=RUNS):
        """Route *index*'s scope here; a new watch replays the journal from
        the index's mark, or starts with a full listing."""
        scope = (area, app_key(index.app_name))
        with self._lock:
            if self._indexes.get(scope) is index:
                return
        index.journaled = True
        since = self._resumable(index)
        with self._lock:
            self._indexes[scope] = index
            if since is not None:
                self._replays[scope] = since
        if since is None:
            index.reconcile()

    def _resumable(self, index):
        """The journal mark *index* resumes from, None when it cannot (an
        elected workspace: its leader reconciles when it takes over)."""
        resume = getattr(index, "resume_journal", None)
        if resume is None or self._election is not None:
            return None
        oldest_sec = self._clock() - self._retain_sec + REPLAY_MARGIN_SEC + self._skew_sec
        return resume(int(oldest_sec * 1000))

    def unwatch(self, index, area=RUNS):
        with self._lock:
            scope = (area, app_key(index.app_name))
            if self._indexes.get(scope) is index:
                del self._indexes[scope]

    def feed_reports(self, reports):
        """Feed *reports* (``feed(entries, overflow, cursor)``) every tick."""
        self._reports = reports

    def receive(self, payload):
        """Route a relayed ``<scope>|<name>`` hint to the watched index."""
        where, name = payload.rsplit("|", 1)
        journal_scope, area, key = where.rsplit("/", 2)
        if journal_scope != self._scope:
            return
        if area in _REPORT_AREAS:
            scope = (area, key)
            self._feed({scope: {name}}, set()) if name else self._feed({}, {scope})
            return
        with self._lock:
            index = self._indexes.get((area, key))
        if index is not None:
            index.hint(name) if name else index.reconcile()

    def tick(self):
        if not self._lead():
            self._feed({}, set())  # relayed entries arrive through receive()
            return
        first = self._reader.cursor["last_seen_ms"] is None
        with self._lock:
            replays, self._replays = self._replays, {}
        self._replay(replays)
        result = self._reader.tick()
        with self._lock:
            indexes = dict(self._indexes)
            replaying = set(self._replays)  # watched since: replayed next tick
        _route(result, indexes, self._send)
        reached = self._reader.cursor["last_seen_ms"]
        for scope, index in indexes.items():
            journal_at = None if scope in replaying else getattr(index, "journal_at", None)
            if journal_at is not None:
                journal_at(reached)
        if first or result.entries or result.overflow:
            self._cache.kv_put(self._scope, _CURSOR_FINGERPRINT, self._reader.cursor)
        self._feed_tick(result)

    def _replay(self, replays):
        """Hint each replayed scope's index with the journal since its mark."""
        for scope, since in list(replays.items()):
            with self._lock:
                index = self._indexes.get(scope)
            try:
                if index is not None:
                    _route(self._new_reader({"last_seen_ms": since}).tick(), {scope: index})
            except BaseException:
                with self._lock:  # the next tick tries again
                    for left, mark in replays.items():
                        self._replays.setdefault(left, mark)
                raise
            del replays[scope]

    def _feed_tick(self, result):
        entries = {scope: {key.name for key in keys}
                   for scope, keys in result.entries.items() if scope[0] in _REPORT_AREAS}
        overflow = {scope for scope in result.overflow if scope[0] in _REPORT_AREAS}
        self._feed(entries, overflow, self._reader.cursor)

    def _feed(self, entries, overflow, cursor=None):
        if self._reports is not None:
            self._reports.feed(entries, overflow, cursor)

    def _lead(self):
        if self._election is None:
            return True
        leading = self._election.lead(self._scope)
        if leading and not self._leading:
            self._reader = self._new_reader(self._saved_cursor())
        self._leading = leading
        return leading

    def _send(self, scope, name):
        if self._relay is not None:
            self._relay(f"{self._scope}/{scope[0]}/{scope[1]}|{name}")

    def _saved_cursor(self):
        return self._cache.kv_get(self._scope, _CURSOR_FINGERPRINT) or {}


def _route(result, indexes, send=None):
    """Hint *indexes* (by scope) with *result*'s entries, relaying each to *send*."""
    for scope, keys in result.entries.items():
        index = indexes.get(scope)
        for key in keys:
            if index is not None:
                index.hint(key.name)
            if send is not None:
                send(scope, key.name)
    for scope in result.overflow:
        index = indexes.get(scope)
        overflowed = getattr(index, "overflowed", None)
        if overflowed is not None:
            overflowed(result.overflow_names.get(scope, set()))
        elif index is not None:
            index.reconcile()
        if send is not None:
            send(scope, "")
