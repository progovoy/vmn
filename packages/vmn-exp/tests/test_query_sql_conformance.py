"""The SQL backend of the query language agrees with ``filter_rows`` (plan 11 §4.4).

Every test of the query-language corpus runs here once more with the module's
``filter_rows``/``compile_query`` swapped for checking twins: each call is also
answered by :func:`vmn_exp.ui.query_sql.compile_sql` over the same rows stored
as ``jsonb`` in Postgres, and the two answers must be identical.
"""
import functools
import inspect
import json

import pytest

import test_experiment_query
import test_experiment_query_inputs_env
import test_fix_query
from pg_fixture import pg_dsn, pg_server_dsn  # noqa: F401
from vmn_exp.core import query
from vmn_exp.ui.query_sql import compile_sql

CORPUS = (test_experiment_query, test_experiment_query_inputs_env, test_fix_query)


def _cases():
    for module in CORPUS:
        for name, fn in sorted(vars(module).items()):
            if not (name.startswith("test_") and inspect.isfunction(fn)):
                continue
            marks = [m for m in getattr(fn, "pytestmark", []) if m.name == "parametrize"]
            if not marks:
                yield pytest.param(module, fn, {}, id=f"{module.__name__}::{name}")
                continue
            argname, values = marks[0].args
            for i, value in enumerate(values):
                yield pytest.param(
                    module, fn, {argname: value}, id=f"{module.__name__}::{name}[{i}]"
                )


class _SqlTwin:
    def __init__(self, conn):
        self.conn = conn
        conn.execute("CREATE TEMP TABLE q_rows (pos int PRIMARY KEY, data jsonb NOT NULL)")
        self.checks = 0

    def positions(self, rows, text):
        """Indices of *rows* the SQL backend matches."""
        where, params = compile_sql(text)
        self.conn.execute("TRUNCATE q_rows")
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO q_rows (pos, data) VALUES (%s, %s::jsonb)",
                [(i, json.dumps(row, default=str)) for i, row in enumerate(rows)],
            )
        found = self.conn.execute(
            f"SELECT pos FROM q_rows WHERE {where} ORDER BY pos", params
        ).fetchall()
        self.checks += 1
        return [pos for (pos,) in found]

    def filter_rows(self, rows, text, extra=None):
        result = query.filter_rows(rows, text, extra)
        if text and text.strip():
            expected = [i for i, row in enumerate(rows) if any(row is r for r in result)]
            assert self.positions(rows, text) == expected, text
        return result

    @functools.lru_cache(maxsize=None)
    def compile_query(self, text):
        predicate = query.compile_query(text)

        def checked(row):
            answer = predicate(row)
            assert self.positions([row], text) == ([0] if answer else []), text
            return answer

        return checked


@pytest.fixture
def twin(pg_dsn):  # noqa: F811
    import psycopg

    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        yield _SqlTwin(conn)


@pytest.mark.parametrize("module,fn,kwargs", list(_cases()))
def test_sql_backend_matches_python(twin, monkeypatch, module, fn, kwargs):
    monkeypatch.setattr(module, "filter_rows", twin.filter_rows, raising=False)
    monkeypatch.setattr(module, "compile_query", twin.compile_query, raising=False)
    fn(**kwargs)


def test_the_corpus_actually_reaches_postgres(twin, monkeypatch):
    monkeypatch.setattr(test_experiment_query, "filter_rows", twin.filter_rows)
    test_experiment_query.test_and_composition()
    assert twin.checks == 1
