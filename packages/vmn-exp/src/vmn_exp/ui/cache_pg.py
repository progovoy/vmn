#!/usr/bin/env python3
"""A :class:`~vmn_exp.core.cache_store.CacheStore` on Postgres (plan 11 §4.2).

Same contract as :class:`~vmn_exp.core.index_store.SqliteStore`: it never
raises — an unreachable database behaves as empty and reconnects on the next
call. A scope is an app name or ``(workspace_id, app)``; ``org_id`` is the
store's org (0 in single tenancy), or the request's
(:func:`~vmn_exp.ui.tenancy.current_org`), bound per transaction for RLS. Each save
is one transaction that bumps the scope's generation and
``NOTIFY vmn_gen, '<workspace_id>:<app>'`` (delivered on commit). A cache
schema change TRUNCATEs the cache tables, never the control-plane ones.
"""
import json
import logging
import threading

from vmn_exp.core import index_store
from vmn_exp.core.cache_store import FULL_LOAD
from vmn_exp.core.index_store import _state_of, _without_state
from vmn_exp.core.index_store_schema import SCHEMA_VERSION
from vmn_exp.ui import migrations
from vmn_exp.ui.control_plane_pg import PostgresControlPlane  # noqa: F401
from vmn_exp.ui.tenancy import bind_org, effective_org

_LOGGER = logging.getLogger(__name__)
_CACHE_TABLES = "vmn_records, vmn_run_states, vmn_tombstones, vmn_scope_gen, vmn_kv"
_SCOPE = "org_id = %s AND workspace_id = %s AND app = %s"


def scope_key(scope, org_id=0):
    """``(org_id, workspace_id, app)`` of *scope*."""
    if isinstance(scope, tuple):
        workspace_id, app = scope
        return (org_id, workspace_id, app)
    return (org_id, 0, scope)


def _kv_key(scope, org_id=0):
    org, workspace_id, name = scope_key(scope, org_id)
    return (org, workspace_id, str(name))


def _jsonable(value):
    # jsonb rejects NaN/Infinity: store them as null, like the API serves them.
    text = json.dumps(value, default=str)
    return json.dumps(json.loads(text, parse_constant=lambda _: None))


def _ensure_cache_version(conn):
    with conn.transaction():
        conn.execute("LOCK TABLE vmn_cache_meta")
        row = conn.execute(
            "SELECT v FROM vmn_cache_meta WHERE k = 'schema_version'"
        ).fetchone()
        if row and row[0] == SCHEMA_VERSION:
            return
        conn.execute(f"TRUNCATE {_CACHE_TABLES}")
        conn.execute(
            "INSERT INTO vmn_cache_meta (k, v) VALUES ('schema_version', %s)"
            " ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v",
            (SCHEMA_VERSION,),
        )


class PostgresStore:
    def __init__(self, dsn, org_id=0):
        self._dsn = dsn
        self._default_org = org_id
        self._lock = threading.Lock()
        self._conn = None

    def _connection(self):
        if self._conn is None or self._conn.closed:
            conn = migrations.connect(self._dsn)
            _ensure_cache_version(conn)
            self._conn = conn
        return self._conn

    @property
    def _org(self):
        return effective_org(self._default_org)

    def _run(self, op, default, what):
        with self._lock:
            try:
                conn = self._connection()
                with conn.transaction():
                    bind_org(conn, self._org)
                    return op(conn)
            except Exception:
                _LOGGER.debug("Could not %s the Postgres cache", what, exc_info=True)
                self._drop_connection()
                return default

    def _drop_connection(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _key(self, scope):
        return scope_key(scope, self._org)

    def purge_workspace(self, workspace_id):
        """Drop every cache row of *workspace_id* (a disconnected workspace)."""

        def purge(conn):
            with conn.transaction():
                for table in _CACHE_TABLES.split(", "):
                    conn.execute(
                        f"DELETE FROM {table} WHERE org_id = %s AND workspace_id = %s",
                        (self._org, workspace_id),
                    )

        self._run(purge, None, "purge")

    def load(self, scope):
        return self._run(lambda c: _records(c, self._key(scope)), {}, "read")

    def generation(self, scope):
        return self._run(lambda c: _gen_row(c, self._key(scope))[0], 0, "read")

    def load_since(self, scope, generation):
        return self._run(
            lambda c: _delta(c, self._key(scope), generation), ({}, set(), 0), "read"
        )

    def save(self, scope, changed, removed, states=None):
        states = states or {}
        if not (changed or removed or states):
            return
        self._run(lambda c: _save(c, self._key(scope), changed, removed, states), None, "write")

    def cache_version(self):
        """The ``vmn_cache_meta`` schema version; ``""`` when the row is gone,
        None when the database is unreachable."""

        def query(conn):
            row = conn.execute(
                "SELECT v FROM vmn_cache_meta WHERE k = 'schema_version'").fetchone()
            return row[0] if row else ""

        return self._run(query, None, "read")

    def reset_cache(self):
        """Reconnect, re-checking the cache schema (a truncated or foreign
        cache is emptied and re-stamped)."""
        with self._lock:
            self._drop_connection()

    def replace_scope(self, scope, records, floor=0):
        """Make *records* the scope's whole content in one transaction, under
        a generation past *floor*: followers see the new set at once, never a
        half-built one (the rebuild's shadow generation)."""
        self._run(lambda c: _replace(c, self._key(scope), records, floor), None, "write")

    def kv_get(self, scope, fingerprint):
        def query(conn):
            row = conn.execute(
                "SELECT fingerprint, payload FROM vmn_kv"
                " WHERE org_id = %s AND workspace_id = %s AND scope = %s",
                _kv_key(scope, self._org),
            ).fetchone()
            return row[1] if row and row[0] == fingerprint else None

        return self._run(query, None, "read")

    def kv_put(self, scope, fingerprint, payload):
        self._run(
            lambda c: c.execute(
                "INSERT INTO vmn_kv (org_id, workspace_id, scope, fingerprint, payload)"
                " VALUES (%s, %s, %s, %s, %s::jsonb)"
                " ON CONFLICT (org_id, workspace_id, scope) DO UPDATE"
                " SET fingerprint = EXCLUDED.fingerprint, payload = EXCLUDED.payload",
                _kv_key(scope, self._org) + (fingerprint, _jsonable(payload)),
            ),
            None,
            "write",
        )


def _records(conn, key, keys=None):
    rows = conn.execute(f"SELECT key, data FROM vmn_records WHERE {_SCOPE}", key)
    records = {
        k: dict(_state_of({}), **data) for k, data in rows if keys is None or k in keys
    }
    for k, data in conn.execute(f"SELECT key, data FROM vmn_run_states WHERE {_SCOPE}", key):
        if k in records:
            records[k].update(data)
    return records


def _gen_row(conn, key):
    row = conn.execute(f"SELECT gen, horizon FROM vmn_scope_gen WHERE {_SCOPE}", key).fetchone()
    return row or (0, 0)


def _delta(conn, key, generation):
    with conn.transaction():
        gen, horizon = _gen_row(conn, key)
        if generation < horizon:
            return _records(conn, key), FULL_LOAD, gen
        keys = {
            k
            for table in ("vmn_records", "vmn_run_states")
            for (k,) in conn.execute(
                f"SELECT key FROM {table} WHERE {_SCOPE} AND seq > %s", key + (generation,)
            )
        }
        removed = {
            k for (k,) in conn.execute(
                f"SELECT key FROM vmn_tombstones WHERE {_SCOPE} AND seq > %s",
                key + (generation,),
            )
        }
        changed = _records(conn, key, keys) if keys else {}
        return changed, removed, gen


def _save(conn, key, changed, removed, states):
    with conn.transaction():
        (seq,) = conn.execute(
            "INSERT INTO vmn_scope_gen (org_id, workspace_id, app, gen) VALUES (%s, %s, %s, 1)"
            " ON CONFLICT (org_id, workspace_id, app) DO UPDATE"
            " SET gen = vmn_scope_gen.gen + 1 RETURNING gen",
            key,
        ).fetchone()
        _upsert(conn, "vmn_records", key, seq, changed, _without_state)
        _upsert(conn, "vmn_run_states", key, seq, states, _state_of)
        _forget(conn, key, seq, removed)
        _trim_tombstones(conn, key)
        conn.execute("SELECT pg_notify('vmn_gen', %s)", (f"{key[1]}:{key[2]}",))


def _replace(conn, key, records, floor):
    with conn.transaction():
        (seq,) = conn.execute(
            "INSERT INTO vmn_scope_gen (org_id, workspace_id, app, gen) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (org_id, workspace_id, app) DO UPDATE"
            " SET gen = GREATEST(vmn_scope_gen.gen, %s) + 1 RETURNING gen",
            key + (floor + 1, floor),
        ).fetchone()
        stale = {k for (k,) in conn.execute(
            f"SELECT key FROM vmn_records WHERE {_SCOPE}", key)} - set(records)
        _upsert(conn, "vmn_records", key, seq, records, _without_state)
        _upsert(conn, "vmn_run_states", key, seq, records, _state_of)
        _forget(conn, key, seq, stale)
        conn.execute("SELECT pg_notify('vmn_gen', %s)", (f"{key[1]}:{key[2]}",))


def _upsert(conn, table, key, seq, records, shape):
    if not records:
        return
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {table} (org_id, workspace_id, app, key, data, seq)"
            " VALUES (%s, %s, %s, %s, %s::jsonb, %s)"
            " ON CONFLICT (org_id, workspace_id, app, key) DO UPDATE"
            " SET data = EXCLUDED.data, seq = EXCLUDED.seq",
            [key + (k, _jsonable(shape(r)), seq) for k, r in records.items()],
        )
        if table == "vmn_records":
            cur.executemany(
                f"DELETE FROM vmn_tombstones WHERE {_SCOPE} AND key = %s",
                [key + (k,) for k in records],
            )


def _forget(conn, key, seq, removed):
    if not removed:
        return
    gone = [key + (k,) for k in removed]
    with conn.cursor() as cur:
        for table in ("vmn_records", "vmn_run_states"):
            cur.executemany(f"DELETE FROM {table} WHERE {_SCOPE} AND key = %s", gone)
        cur.executemany(
            "INSERT INTO vmn_tombstones (org_id, workspace_id, app, key, seq, ts)"
            " VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (org_id, workspace_id, app, key) DO UPDATE"
            " SET seq = EXCLUDED.seq, ts = EXCLUDED.ts",
            [g + (seq, index_store._now()) for g in gone],
        )


def _trim_tombstones(conn, key):
    cutoff = key + (index_store._now() - index_store.TOMBSTONE_TTL_SEC,)
    (newest,) = conn.execute(
        f"SELECT MAX(seq) FROM vmn_tombstones WHERE {_SCOPE} AND ts < %s", cutoff
    ).fetchone()
    if newest is None:
        return
    conn.execute(f"DELETE FROM vmn_tombstones WHERE {_SCOPE} AND ts < %s", cutoff)
    conn.execute(
        f"UPDATE vmn_scope_gen SET horizon = GREATEST(horizon, %s) WHERE {_SCOPE}",
        (newest,) + key,
    )
