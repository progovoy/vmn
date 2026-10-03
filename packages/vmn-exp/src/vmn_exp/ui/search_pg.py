#!/usr/bin/env python3
"""Cross-workspace search rows in Postgres (``vmn_search_rows``), filtered by
the query language compiled to SQL (:mod:`vmn_exp.ui.query_sql`).

An app's rows are rewritten whenever its index snapshot's generation moves
past the one last synced here; :meth:`PgRowSearch.search` then answers the
whole query in one statement.
"""
import threading

from vmn_exp.ui import migrations
from vmn_exp.ui.cache_pg import _jsonable
from vmn_exp.ui.query_sql import compile_sql

_NOT_ARCHIVED = " AND NOT COALESCE(data -> 'archived' = 'true'::jsonb, false)"


class PgRowSearch:
    def __init__(self, dsn):
        self._conn = migrations.connect(dsn)
        self._lock = threading.Lock()
        self._synced = {}  # (workspace, app) -> generation

    def sync(self, workspace, app, generation, rows_of):
        """Store *rows_of()* as *workspace*/*app*'s rows unless *generation*
        is already there."""
        key = (workspace, app)
        if self._synced.get(key) == generation:
            return
        rows = rows_of()
        with self._lock, self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM vmn_search_rows WHERE workspace = %s AND app = %s", key
            )
            cur.executemany(
                "INSERT INTO vmn_search_rows (workspace, app, verstr, pos, data)"
                " VALUES (%s, %s, %s, %s, %s::jsonb)",
                [key + (row["verstr"], i, _jsonable(row)) for i, row in enumerate(rows)],
            )
        self._synced[key] = generation

    def search(self, workspaces, text, limit, archived=False):
        """Up to *limit* ``(workspace, app, row)`` of *workspaces* matching *text*."""
        where, params = compile_sql(text, column="data")
        params.update(_ws=list(workspaces), _limit=limit)
        sql = (
            "SELECT workspace, app, data FROM vmn_search_rows"
            f" WHERE workspace = ANY(%(_ws)s) AND {where}"
            + ("" if archived else _NOT_ARCHIVED)
            + " ORDER BY workspace, app, pos LIMIT %(_limit)s"
        )
        with self._lock:
            return self._conn.execute(sql, params).fetchall()
