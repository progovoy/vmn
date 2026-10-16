#!/usr/bin/env python3
"""Where a cache rebuild writes, and how it switches over (plan 11 §4.6).

Each target hands the rebuild a store per app, takes each built index, and
switches every app at once in :meth:`commit`, so a reader never sees a
half-built cache: SQLite builds a new generation file beside the live one and
flips the pointer to it (:mod:`vmn_exp.core.sqlite_files`; the old file goes
once nothing holds it open); Postgres publishes each scope as one transaction
under a generation past any a follower holds (the shadow generation). Without
a persisted cache the rebuild only lives in memory.
"""
from vmn_exp.core import sqlite_files
from vmn_exp.core.index_store import SqliteStore


class MemoryTarget:
    def store_for(self, app):
        return SqliteStore(None)

    def built(self, app, index):
        pass

    def commit(self):
        pass

    def live_store(self, app):
        return None  # keep the built index's own (no-op) store


class SqliteSwap:
    def __init__(self, path):
        self.path = path
        self._new = sqlite_files.new_generation(path)
        self._stores = []

    def store_for(self, app):
        store = SqliteStore(self._new)
        self._stores.append(store)
        return store

    def built(self, app, index):
        pass

    def commit(self):
        for store in self._stores:
            store.close()  # checkpoints the WAL into the file
        sqlite_files.flip(self.path, self._new)
        sqlite_files.sweep(self.path)

    def live_store(self, app):
        return SqliteStore(self.path)


class PgShadow:
    def __init__(self, store, health, scope_of):
        self._store, self._health, self._scope_of = store, health, scope_of
        self._built = {}

    def store_for(self, app):
        return SqliteStore(None)

    def built(self, app, index):
        self._built[app] = index.records

    def commit(self):
        self._store.reset_cache()
        floor = self._health.floor()
        for app, records in self._built.items():
            self._store.replace_scope(self._scope_of(app), records, floor=floor)

    def live_store(self, app):
        return self._store
