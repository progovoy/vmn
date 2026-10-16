#!/usr/bin/env python3
""":class:`ControlPlaneStore` on Postgres (tables from migrations 0002_identity,
0003_audit, 0004_tenancy, 0006_control_plane_queries).

Every call is one transaction on a connection of the DSN's pool
(:mod:`vmn_exp.ui.pg_pool`), bound to the request's org
(:func:`~vmn_exp.ui.tenancy.current_org`), else the store's *org_id*. The
sweeps run in every org (they are server work, not a request's), one org per
transaction so row-level security holds. Credential lookups and sweeps use the
0006 indexes; ``vmn_settings`` (the server key) belongs to no org.
"""
from vmn_exp.ui import pg_pool
from vmn_exp.ui.control_plane import (
    _NON_EXPIRING, _TABLES, EXPIRING, SCAN_BATCH, ControlPlaneStore, keyset_scan,
)
from vmn_exp.ui.tenancy import SINGLE_TENANT_ORG, DefaultOrg, enable_rls


class PostgresControlPlane(DefaultOrg, ControlPlaneStore):
    # The id is unique across orgs (0006): one index probe.
    CREDENTIAL_SQL = "SELECT org_id FROM {table} WHERE id = %s"
    PAGE_SQL = ("SELECT doc FROM {table} WHERE org_id = %s"
                " ORDER BY created DESC LIMIT %s OFFSET %s")
    _SCAN_SQL = ("SELECT created, doc FROM {table} WHERE org_id = %s AND created > %s"
                 " ORDER BY created LIMIT %s")

    def __init__(self, dsn, org_id=0):
        from psycopg.types.json import Jsonb

        super().__init__()
        self._jsonb = Jsonb
        self._default_org = org_id
        self._dsn = dsn

    def _tx(self, org=None, org_bound=True):
        if org_bound:
            return pg_pool.org_tx(self._dsn, self._org if org is None else org)
        return pg_pool.org_tx(self._dsn, None)

    def enable_rls(self):
        """Turn the tenancy row-level security policies on (``tenancy: multi``)."""
        with pg_pool.pool(self._dsn).connection() as conn:
            enable_rls(conn)

    def put(self, kind, key, doc, expires_at=None):
        table, cols = _TABLES[kind], ["org_id", "id", "doc"]
        args = [self._org, key, self._jsonb(doc)]
        if kind not in _NON_EXPIRING:
            cols, args = cols + ["expires_at"], args + [expires_at or 0]
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[2:])
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
            f" ON CONFLICT (org_id, id) DO UPDATE SET {updates}"
        )
        with self._tx() as db:
            db.execute(sql, args)

    def get(self, kind, key, now=None):
        with self._tx() as db:
            return self._get(db, kind, key, now)

    def pop(self, kind, key, now=None):
        # One statement: two replicas popping one key can't both get it.
        expiry = "0" if kind in _NON_EXPIRING else "expires_at"
        with self._tx() as db:
            row = db.execute(f"DELETE FROM {_TABLES[kind]} WHERE org_id = %s AND id = %s"
                             f" RETURNING doc, {expiry}", (self._org, key)).fetchone()
        if row is None or (kind not in _NON_EXPIRING and now is not None and row[1] <= now):
            return None
        return row[0]

    def delete(self, kind, key):
        with self._tx() as db:
            cur = db.execute(f"DELETE FROM {_TABLES[kind]} WHERE org_id = %s AND id = %s", (self._org, key))
            return cur.rowcount > 0

    def list(self, kind):
        with self._tx() as db:
            rows = db.execute(
                f"SELECT doc FROM {_TABLES[kind]} WHERE org_id = %s ORDER BY created", (self._org,)
            )
            return [doc for (doc,) in rows]

    def page(self, kind, offset, limit):
        with self._tx() as db:
            rows = db.execute(self.PAGE_SQL.format(table=_TABLES[kind]), (self._org, limit, offset))
            return [doc for (doc,) in rows]

    def count(self, kind):
        with self._tx() as db:
            return db.execute(
                f"SELECT count(*) FROM {_TABLES[kind]} WHERE org_id = %s", (self._org,)
            ).fetchone()[0]

    def scan(self, kind, batch=SCAN_BATCH):
        # The org is the caller's, bound now: a streamed response iterates later.
        org, sql = self._org, self._SCAN_SQL.format(table=_TABLES[kind])

        def fetch(last):
            with self._tx(org) as db:
                return db.execute(sql, (org, last, batch)).fetchall()

        return keyset_scan(fetch, batch)

    def sweep_expired(self, now):
        for org in self._orgs():
            with self._tx(org) as db:
                for kind in EXPIRING:
                    db.execute(f"DELETE FROM {_TABLES[kind]} WHERE org_id = %s"
                               " AND expires_at <= %s", (org, now))

    def delete_keys_below(self, kind, bound):
        for org in self._orgs():
            with self._tx(org) as db:
                db.execute(f"DELETE FROM {_TABLES[kind]} WHERE org_id = %s AND id < %s",
                           (org, bound))

    def _load_server_key(self, name, fresh):
        with self._tx(org_bound=False) as db:
            db.execute("INSERT INTO vmn_settings (k, v) VALUES (%s, %s)"
                       " ON CONFLICT (k) DO NOTHING", (name, fresh))
            return db.execute("SELECT v FROM vmn_settings WHERE k = %s", (name,)).fetchone()[0]

    def credential_org(self, kind, key):
        # tenancy.enable_rls's vmn_credential_lookup policy lets this one id through in any org.
        with self._tx(org_bound=False) as db:
            db.execute("SELECT set_config('app.credential_id', %s, true)", (key,))
            row = db.execute(self.CREDENTIAL_SQL.format(table=_TABLES[kind]), (key,)).fetchone()
        return row[0] if row else None

    def _orgs(self):
        """Every org with rows: the single-tenant org and each of ``vmn_orgs``."""
        with self._tx(org_bound=False) as db:
            ids = [org for (org,) in db.execute("SELECT id FROM vmn_orgs")]
        return [SINGLE_TENANT_ORG] + ids

    def _get(self, db, kind, key, now):
        sql = f"SELECT doc FROM {_TABLES[kind]} WHERE org_id = %s AND id = %s"
        args = [self._org, key]
        if kind not in _NON_EXPIRING and now is not None:
            sql += " AND expires_at > %s"
            args.append(now)
        row = db.execute(sql, args).fetchone()
        return row[0] if row else None
