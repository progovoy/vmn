#!/usr/bin/env python3
"""Cross-workspace search rows in Postgres (``vmn_search_rows``), filtered by
the query language compiled to SQL (:mod:`vmn_exp.ui.query_sql`).

Rows belong to the bound org (``org_id``, row-level security in multi
tenancy). :meth:`PgRowSearch.sync` rewrites an app's rows in place: one
``INSERT … ON CONFLICT`` of the rows and one ``DELETE`` of the rest, under a
transaction lock per app. Only the replica leading the app's index calls it,
after a refresh (:mod:`vmn_exp.ui.search_rows_writer`); requests only read.
:meth:`PgRowSearch.search` then answers the whole query in one statement.
Each call takes a connection from the DSN's pool (:mod:`vmn_exp.ui.pg_pool`).
"""
from vmn_exp.ui import pg_pool
from vmn_exp.ui.cache_pg import _jsonable
from vmn_exp.ui.query_sql import compile_sql
from vmn_exp.ui.tenancy import bind_org, effective_org

_NOT_ARCHIVED = " AND NOT COALESCE(data -> 'archived' = 'true'::jsonb, false)"
_UPSERT = (
    "INSERT INTO vmn_search_rows (org_id, workspace, app, verstr, pos, data)"
    " SELECT %s, %s, %s, v, p, d"
    " FROM unnest(%s::text[], %s::integer[], %s::jsonb[]) AS r (v, p, d)"
    " ON CONFLICT (org_id, workspace, app, verstr)"
    " DO UPDATE SET pos = EXCLUDED.pos, data = EXCLUDED.data"
)
_DELETE_REST = (
    "DELETE FROM vmn_search_rows WHERE org_id = %s AND workspace = %s AND app = %s"
    " AND NOT (verstr = ANY(%s::text[]))"
)


class PgRowSearch:
    def __init__(self, dsn):
        self._dsn = dsn

    def sync(self, workspace, app, rows):
        """Store *rows* as *workspace*/*app*'s rows."""
        key = (effective_org(0), workspace, app)
        lock = "search:%s:%s:%s" % key
        verstrs = [row["verstr"] for row in rows]
        with pg_pool.pool(self._dsn).connection() as conn, conn.transaction():
            bind_org(conn, key[0])
            # Serializes writers across a leader handover (and git workspaces'
            # replicas, which each write their own index's rows).
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock,))
            conn.execute(_UPSERT, key + (
                verstrs, list(range(len(rows))), [_jsonable(row) for row in rows]))
            conn.execute(_DELETE_REST, key + (verstrs,))

    def search(self, workspaces, text, limit, archived=False):
        """Up to *limit* ``(workspace, app, row)`` of *workspaces* matching *text*."""
        where, params = compile_sql(text, column="data")
        org = effective_org(0)
        params.update(_org=org, _ws=list(workspaces), _limit=limit)
        sql = (
            "SELECT workspace, app, data FROM vmn_search_rows"
            f" WHERE org_id = %(_org)s AND workspace = ANY(%(_ws)s) AND {where}"
            + ("" if archived else _NOT_ARCHIVED)
            + " ORDER BY workspace, app, pos LIMIT %(_limit)s"
        )
        with pg_pool.pool(self._dsn).connection() as conn, conn.transaction():
            bind_org(conn, org)
            return conn.execute(sql, params).fetchall()
