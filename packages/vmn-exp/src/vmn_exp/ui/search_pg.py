#!/usr/bin/env python3
"""Cross-workspace search rows in Postgres (``vmn_search_rows``), filtered by
the query language compiled to SQL (:mod:`vmn_exp.ui.query_sql`).

Rows belong to the bound org (``org_id``, row-level security in multi
tenancy). :meth:`PgRowSearch.write` upserts rows of an app (one
``INSERT … ON CONFLICT``) and deletes the named removed ones, or, as
:meth:`PgRowSearch.sync`, every row it was not given, under a transaction lock
per app. Only the replica leading the app's index calls it,
after a refresh (:mod:`vmn_exp.ui.search_rows_writer`); requests only read.
:meth:`PgRowSearch.search` then answers the whole query in one statement.
Each call takes a connection from the DSN's pool (:mod:`vmn_exp.ui.pg_pool`).
"""
from vmn_exp.ui import pg_pool
from vmn_exp.ui.cache_pg import _jsonable
from vmn_exp.ui.query_sql import compile_sql
from vmn_exp.ui.tenancy import effective_org

_NOT_ARCHIVED = " AND NOT COALESCE(data -> 'archived' = 'true'::jsonb, false)"
_UPSERT = (
    "INSERT INTO vmn_search_rows (org_id, workspace, app, verstr, pos, data)"
    " SELECT %s, %s, %s, v, p, d"
    " FROM unnest(%s::text[], %s::integer[], %s::jsonb[]) AS r (v, p, d)"
    " ON CONFLICT (org_id, workspace, app, verstr)"
    " DO UPDATE SET pos = EXCLUDED.pos, data = EXCLUDED.data"
)
_DELETE = "DELETE FROM vmn_search_rows WHERE org_id = %s AND workspace = %s AND app = %s"
_DELETE_REST = _DELETE + " AND NOT (verstr = ANY(%s::text[]))"
_DELETE_LISTED = _DELETE + " AND verstr = ANY(%s::text[])"


def search_entries(rows):
    """``(verstr, pos, data)`` of each of *rows*, *data* its stored JSON."""
    return [(row["verstr"], pos, _jsonable(row)) for pos, row in enumerate(rows)]


class PgRowSearch:
    def __init__(self, dsn):
        self._dsn = dsn

    def sync(self, workspace, app, rows):
        """Store *rows* as *workspace*/*app*'s rows."""
        self.write(workspace, app, search_entries(rows))

    def write(self, workspace, app, entries, removed=None):
        """Upsert *entries* (:func:`search_entries`) of *workspace*/*app* and
        delete the *removed* verstrs, or every row not in *entries* when
        *removed* is ``None``."""
        key = (effective_org(0), workspace, app)
        verstrs, positions, data = (list(c) for c in zip(*entries)) if entries else ([], [], [])
        with pg_pool.org_tx(self._dsn, key[0]) as conn:
            # Serializes writers across a leader handover (and git workspaces'
            # replicas, which each write their own index's rows).
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("search:%s:%s:%s" % key,))
            if entries:
                conn.execute(_UPSERT, key + (verstrs, positions, data))
            if removed is None:
                conn.execute(_DELETE_REST, key + (verstrs,))
            elif removed:
                conn.execute(_DELETE_LISTED, key + (list(removed),))

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
        with pg_pool.org_tx(self._dsn, org) as conn:
            return conn.execute(sql, params).fetchall()
