"""PgRowSearch.write: upserts the given rows and deletes only the named ones
(the incremental path of SearchRowsWriter)."""
import json

import pytest

pytest.importorskip("psycopg")

from vmn_exp.ui.search_pg import PgRowSearch  # noqa: E402


def _entry(verstr, pos):
    return (verstr, pos, json.dumps({"verstr": verstr, "archived": False}))


def _hits(search):
    return [row["verstr"] for (_, _, row) in search.search(["ws"], "", 10)]


def test_write_keeps_rows_it_was_not_given(pg_dsn):
    search = PgRowSearch(pg_dsn)
    search.write("ws", "app", [_entry("a", 0), _entry("b", 1), _entry("c", 2)])
    search.write("ws", "app", [_entry("d", 3)], removed=["b"])
    assert _hits(search) == ["a", "c", "d"]


def test_write_without_removed_is_a_full_sync(pg_dsn):
    search = PgRowSearch(pg_dsn)
    search.write("ws", "app", [_entry("a", 0), _entry("b", 1)])
    search.write("ws", "app", [_entry("c", 0)])
    assert _hits(search) == ["c"]
