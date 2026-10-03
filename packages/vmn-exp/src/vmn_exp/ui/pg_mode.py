#!/usr/bin/env python3
"""``vmn-exp ui --db postgresql://...``: store workspaces' indexes in the
shared Postgres cache, refreshed by one elected replica (plan 11 §4.2-4.3).

:class:`PgIndexes` hands out one :class:`~vmn_exp.ui.elected_index.ElectedIndex`
per workspace app, over one :class:`~vmn_exp.ui.cache_pg.PostgresStore` and one
:class:`~vmn_exp.ui.pg_election.AdvisoryElection`. Each workspace's apps are
cached under ``(workspace_id, app)``, the id derived from its store URI so
every replica agrees on it. With a background refresher a
:class:`~vmn_exp.ui.pg_listen.PgListener` wakes the followers of a scope the
moment its leader saves (``NOTIFY vmn_gen``). psycopg is only imported on
first use.
"""
import hashlib
import threading

from vmn_exp.ui.tenancy import current_org, org_context

POSTGRES_SCHEMES = ("postgresql://", "postgres://")
_SCOPED = ("load", "generation", "load_since", "save", "replace_scope", "kv_get", "kv_put")


def is_postgres_dsn(dsn):
    return bool(dsn) and dsn.startswith(POSTGRES_SCHEMES)


def workspace_id(ws):
    """A stable positive bigint for *ws* (same store URI, same id)."""
    return int(hashlib.sha256(ws.store.encode()).hexdigest()[:12], 16)


class WorkspaceScopedCache:
    """*store* with every app scope qualified by *ws_id*, each call bound to
    *org_id* (the workspace's org: refresher threads have no request org)."""

    def __init__(self, store, ws_id, org_id=None):
        self._store = store
        self._ws_id = ws_id
        self._org_id = org_id

    def __getattr__(self, name):
        attr = getattr(self._store, name)
        if not callable(attr):
            return attr
        scoped = name in _SCOPED

        def call(*args, **kwargs):
            if scoped:
                args = ((self._ws_id, args[0]),) + args[1:]
            with org_context(self._org_id):
                return attr(*args, **kwargs)

        return call


class PgIndexes:
    def __init__(self, dsn, refresher):
        from vmn_exp.ui.cache_pg import PostgresStore
        from vmn_exp.ui.pg_election import AdvisoryElection

        self._store = PostgresStore(dsn)
        self._election = AdvisoryElection(dsn)
        self._indexes = {}  # (org, workspace name, app) -> ElectedIndex
        self._lock = threading.Lock()
        self._listener = None
        if refresher.background:
            from vmn_exp.ui.pg_listen import PgListener

            self._listener = PgListener(dsn, {"vmn_gen": refresher.wake_scope})

    def index(self, ws, app_name, storage):
        from vmn_exp.ui.elected_index import ElectedIndex

        org_id = current_org()
        key = (org_id, ws.name, app_name)
        with self._lock:
            if key not in self._indexes:
                cache = WorkspaceScopedCache(self._store, workspace_id(ws), org_id)
                self._indexes[key] = ElectedIndex(storage, app_name, cache, self._election)
            return self._indexes[key]

    def forget(self, ws_name):
        with self._lock:
            for key in [k for k in self._indexes if k[1] == ws_name]:
                del self._indexes[key]

    def close(self):
        if self._listener is not None:
            self._listener.stop()
        self._election.close()
