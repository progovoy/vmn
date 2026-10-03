#!/usr/bin/env python3
"""One change-journal reader per store workspace (plan 11 §5.2).

Each :meth:`WorkspaceJournal.tick` lists the store's journal once (whatever
the number of apps) and routes every new entry by ``(area, app)`` to the
watched index of that scope as a ``hint``; entries for scopes nobody watches
are dropped (a later watch starts with a reconcile listing), and a scope that
overflows reconciles instead. The cursor persists in the workspace's
``CacheStore`` kv, so a restart resumes where it stopped.

With an *election* (Postgres mode, plan 11 §4.3) only the replica leading
the workspace's journal ticks; it passes every entry to *relay* as
``<scope>|<name>`` (``NOTIFY vmn_hint``; an empty name asks to reconcile),
and every replica routes those to its own watched indexes with
:meth:`WorkspaceJournal.receive`. A new leader resumes from the shared cursor.
"""
import threading
import time

from vmn_exp.core.journal_reader import JournalReader
from vmn_exp.storage.areas import RUNS, app_key

_CURSOR_FINGERPRINT = "journal-cursor"


class WorkspaceJournal:
    def __init__(self, list_fn, cache, scope, clock=time.time, election=None, relay=None,
                 **reader_kw):
        self._cache, self._scope = cache, f"journal:{scope}"
        self._election, self._relay, self._leading = election, relay, False
        self._new_reader = lambda cursor: JournalReader.from_cursor(
            cursor, list_fn, clock, **reader_kw)
        self._reader = self._new_reader(self._saved_cursor())
        self._indexes = {}  # (area, app key) -> index
        self._lock = threading.Lock()

    def use_cache(self, cache):
        """Keep the cursor in *cache* from now on (the cache was rebuilt)."""
        self._cache = cache
        self._cache.kv_put(self._scope, _CURSOR_FINGERPRINT, self._reader.cursor)

    @property
    def cursor(self):
        return self._reader.cursor

    @property
    def watched(self):
        return bool(self._indexes)

    def watch(self, index, area=RUNS):
        """Route *index*'s scope here; a new watch starts with a full listing."""
        scope = (area, app_key(index.app_name))
        with self._lock:
            if self._indexes.get(scope) is index:
                return
            self._indexes[scope] = index
        index.journaled = True
        index.reconcile()

    def unwatch(self, index, area=RUNS):
        with self._lock:
            scope = (area, app_key(index.app_name))
            if self._indexes.get(scope) is index:
                del self._indexes[scope]

    def receive(self, payload):
        """Route a relayed ``<scope>|<name>`` hint to the watched index."""
        where, name = payload.rsplit("|", 1)
        journal_scope, area, key = where.rsplit("/", 2)
        if journal_scope != self._scope:
            return
        with self._lock:
            index = self._indexes.get((area, key))
        if index is not None:
            index.hint(name) if name else index.reconcile()

    def tick(self):
        if not self._lead():
            return
        first = self._reader.cursor["last_seen_ms"] is None
        result = self._reader.tick()
        with self._lock:
            indexes = dict(self._indexes)
        for scope, keys in result.entries.items():
            index = indexes.get(scope)
            for key in keys:
                if index is not None:
                    index.hint(key.name)
                self._send(scope, key.name)
        for scope in result.overflow:
            if scope in indexes:
                indexes[scope].reconcile()
            self._send(scope, "")
        if first or result.entries or result.overflow:
            self._cache.kv_put(self._scope, _CURSOR_FINGERPRINT, self._reader.cursor)

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
