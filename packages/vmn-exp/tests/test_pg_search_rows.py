"""``vmn_search_rows`` (plan 25 F5): org-scoped under RLS, rewritten in place
(who writes them: test_pg_search_replicas.py)."""
import threading

import pytest

psycopg = pytest.importorskip("psycopg")

from vmn_exp.ui import tenancy  # noqa: E402
from vmn_exp.ui.search_pg import PgRowSearch  # noqa: E402
from vmn_exp.ui.tenancy import org_context  # noqa: E402


def _rows(*verstrs):
    return [{"verstr": v, "archived": False} for v in verstrs]


def _hits(search, org):
    with org_context(org):
        return [row["verstr"] for (_, _, row) in search.search(["ws"], "", 10)]


def test_search_rows_are_isolated_per_org(pg_rls_dsn):
    search = PgRowSearch(pg_rls_dsn)
    with org_context(1):
        search.sync("ws", "app", _rows("a1"))
    with org_context(2):
        search.sync("ws", "app", _rows("b1"))
    assert _hits(search, 1) == ["a1"]
    assert _hits(search, 2) == ["b1"]
    with psycopg.connect(pg_rls_dsn, autocommit=True) as conn:
        (n,) = conn.execute("SELECT count(*) FROM vmn_search_rows").fetchone()
    assert n == 0


def test_search_rows_carry_rls(pg_rls_dsn):
    assert "vmn_search_rows" in tenancy.RLS_TABLES


def test_new_rows_replace_the_old_in_place(pg_dsn):
    search = PgRowSearch(pg_dsn)
    search.sync("ws", "app", _rows("a", "b"))
    search.sync("ws", "app", _rows("c", "b"))
    assert _hits(search, 0) == ["c", "b"]


def test_replicas_syncing_concurrently_end_with_the_last_rows(pg_dsn):
    replicas = [PgRowSearch(pg_dsn) for _ in range(3)]
    errors = []

    def run(search):
        try:
            for gen in range(1, 30):
                search.sync("ws", "app", _rows(*[f"v{gen}.{i}" for i in range(50)]))
        except Exception as exc:  # pragma: no cover - the assertion reports it
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(s,)) for s in replicas]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    assert _hits(replicas[0], 0) == [f"v29.{i}" for i in range(10)]
