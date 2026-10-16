"""A Postgres cache delta reads only the changed records (plan 25 F5)."""
import pytest

psycopg = pytest.importorskip("psycopg")

from vmn_exp.ui import cache_pg  # noqa: E402
from vmn_exp.ui.cache_pg import PostgresStore  # noqa: E402


class _Result(list):
    def fetchone(self):
        return self[0] if self else None

    def fetchall(self):
        return list(self)


class _Tracing:
    """A connection recording ``(sql, rows returned)`` per statement."""

    def __init__(self, conn):
        self._conn = conn
        self.reads = []

    def execute(self, sql, args=None):
        rows = _Result(self._conn.execute(sql, args).fetchall())
        self.reads.append((sql, len(rows)))
        return rows

    def transaction(self):
        return self._conn.transaction()


def test_a_delta_of_three_keys_reads_three_rows(pg_dsn):
    store = PostgresStore(pg_dsn)
    store.save("app", {f"r{i}": {"verstr": f"r{i}"} for i in range(500)}, set(),
               states={f"r{i}": {"run_state": {"state": "running"}} for i in range(500)})
    gen = store.generation("app")
    changed = {f"r{i}": {"verstr": f"r{i}", "note": "x"} for i in (1, 2, 3)}
    store.save("app", changed, set(), states={k: {"run_state": {}} for k in changed})
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        traced = _Tracing(conn)
        got, removed, _ = cache_pg._delta(traced, cache_pg.scope_key("app"), gen)
    assert set(got) == set(changed) and removed == set()
    assert got["r1"]["note"] == "x"
    data_reads = [n for sql, n in traced.reads if "SELECT key, data" in sql]
    assert data_reads == [3, 3]
