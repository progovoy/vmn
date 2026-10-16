#!/usr/bin/env python3
"""Cross-workspace search rows in Postgres (``vmn_search_rows``), filtered by
the query language compiled to SQL (:mod:`vmn_exp.ui.query_sql`).

Rows belong to the request's org (``org_id``, row-level security in multi
tenancy). An app's rows are rewritten whenever its index snapshot's
generation moves past the one last synced here, in place: one
``INSERT … ON CONFLICT`` of the rows and one ``DELETE`` of the rest, under a
transaction lock per app. With an *election* only the replica leading
``search:<org>:<workspace>:<app>`` writes; the others read what it wrote.
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
    def __init__(self, dsn, election=None):
        self._dsn = dsn
        self._election = election
        self._synced = {}  # (org, workspace, app) -> generation

    def sync(self, workspace, app, generation, rows_of):
        """Store *rows_of()* as *workspace*/*app*'s rows unless *generation*
        is already there (or another replica leads their sync)."""
        key = (effective_org(0), workspace, app)
        name = "search:%s:%s:%s" % key
        if self._synced.get(key) == generation or not self._leads(name):
            return
        rows = rows_of()
        verstrs = [row["verstr"] for row in rows]
        with pg_pool.pool(self._dsn).connection() as conn, conn.transaction():
            bind_org(conn, key[0])
            # Serializes writers across a leader handover (or without an election).
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (name,))
            conn.execute(_UPSERT, key + (
                verstrs, list(range(len(rows))), [_jsonable(row) for row in rows]))
            conn.execute(_DELETE_REST, key + (verstrs,))
        self._synced[key] = generation

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

    def _leads(self, name):
        return self._election is None or self._election.lead(name)
