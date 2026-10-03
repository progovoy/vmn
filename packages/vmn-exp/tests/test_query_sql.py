"""``compile_sql``: the query language as a parameterized Postgres predicate."""
import pytest

from vmn_exp.core.query import QueryError
from vmn_exp.ui.query_sql import compile_sql


def test_values_are_parameters_never_sql_text():
    where, params = compile_sql("note ~ \"x'); DROP TABLE t; --\" and metrics.loss < 0.5")
    assert "DROP" not in where
    assert "x'); DROP TABLE t; --" in params.values()
    assert "0.5" not in where


def test_field_names_are_parameters_too():
    where, params = compile_sql('metrics."a\'b" = 1')
    assert "a'b" not in where
    assert ["metrics", "a'b"] in params.values()


def test_column_is_configurable():
    where, _ = compile_sql("idx = 1", column="r.data")
    assert "r.data" in where


def test_empty_query_matches_everything():
    assert compile_sql("") == ("true", {})
    assert compile_sql(None) == ("true", {})


def test_bad_query_raises_query_error():
    with pytest.raises(QueryError):
        compile_sql("statuz = 1")
