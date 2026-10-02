#!/usr/bin/env python3
"""One change-journal reader per store workspace (plan 11 §5.2).

Each :meth:`WorkspaceJournal.tick` lists the store's journal once (whatever
the number of apps) and routes every new entry by ``(area, app)`` to the
watched index of that scope as a ``hint``; entries for scopes nobody watches
are dropped (a later watch starts with a reconcile listing), and a scope that
overflows reconciles instead. The cursor persists in the workspace's
``CacheStore`` kv, so a restart resumes where it stopped.
"""
import threading
import time

from vmn_exp.core.journal_reader import JournalReader
from vmn_exp.storage.areas import RUNS, app_key

_CURSOR_FINGERPRINT = "journal-cursor"


class WorkspaceJournal:
    def __init__(self, list_fn, cache, scope, clock=time.time, **reader_kw):
        self._cache, self._scope = cache, f"journal:{scope}"
        cursor = cache.kv_get(self._scope, _CURSOR_FINGERPRINT) or {}
        self._reader = JournalReader.from_cursor(cursor, list_fn, clock, **reader_kw)
        self._indexes = {}  # (area, app key) -> index
        self._lock = threading.Lock()

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

    def tick(self):
        before = self._reader.cursor
        result = self._reader.tick()
        with self._lock:
            indexes = dict(self._indexes)
        for scope, keys in result.entries.items():
            index = indexes.get(scope)
            for key in keys if index is not None else ():
                index.hint(key.name)
        for scope in result.overflow:
            if scope in indexes:
                indexes[scope].reconcile()
        if self._reader.cursor != before:
            self._cache.kv_put(self._scope, _CURSOR_FINGERPRINT, self._reader.cursor)
