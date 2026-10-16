"""Plan 24 F5: ``intent``/``keywords`` fields and the ``similar("<text>")``
predicate in the query language — parsing and semantics over fake extras.

Neither field is on a lean row: a query reads them through ``filter_rows``'
*extra* (``{key: of(verstr)}``), like ``outputs``. ``similar`` takes a
resolver ``text -> verstrs`` the same way, asked once per distinct text."""
import pytest
from vmn_exp.core.query import ROW_FIELDS, QueryError, filter_rows, parse_query, query_roots
from vmn_exp.ui.query_sql import compile_sql

ROWS = [{"verstr": v, "status": s, "metrics": {}, "params": {}}
        for v, s in (("a", "succeeded"), ("b", "failed"), ("c", "succeeded"))]
INTENTS = {"a": {"text": "Try focal loss", "keywords": ["Class imbalance", "loss"]},
           "b": {"text": "label smoothing", "keywords": []}}


def _extra(**more):
    return {"intent": lambda v: (INTENTS.get(v) or {}).get("text"),
            "keywords": lambda v: (INTENTS.get(v) or {}).get("keywords"), **more}


def _verstrs(text, extra=None):
    return [r["verstr"] for r in filter_rows(ROWS, text, extra=extra or _extra())]


def test_intent_and_keywords_are_query_fields():
    assert {"intent", "keywords"} <= ROW_FIELDS
    assert {"intent", "keywords"} <= query_roots('intent ~ "x" or keywords ~ "y"')


@pytest.mark.parametrize("text, expected", [
    ('intent ~ "FOCAL"', ["a"]),
    ('intent !~ "focal"', ["b", "c"]),
    ('intent = "label smoothing"', ["b"]),
    ("intent = null", ["c"]),
    ('keywords ~ "imbalance"', ["a"]),
    ('keywords ~ "LOSS"', ["a"]),
    ('keywords ~ "smoothing"', []),
    ("keywords = null", ["c"]),
    ('intent ~ "loss" and status = "succeeded"', ["a"]),
])
def test_intent_fields_filter_rows(text, expected):
    assert _verstrs(text) == expected


def test_the_rows_returned_are_the_rows_given():
    [row] = filter_rows(ROWS, 'intent ~ "focal"', extra=_extra())
    assert row is ROWS[0] and "intent" not in row


def test_similar_parses_to_its_own_node():
    assert parse_query('similar("focal loss")') == ("similar", "focal loss")
    assert parse_query("not similar('x') and status = \"failed\"")[0] == "and"
    assert "similar" in query_roots('similar("x")')


@pytest.mark.parametrize("text, message, offset", [
    ("similar()", "similar() takes one quoted text", 8),
    ("similar(1)", "similar() takes one quoted text", 8),
    ('similar("a", "b")', "expected ')'", 11),
    ('similar("a"', "expected ')'", 11),
    ('similar("!! ?")', "similar() needs a word to match", 8),
    ('similar = "a"', "unknown field 'similar'", 0),
    ("similar", "unknown field 'similar'", 0),
])
def test_bad_similar_is_a_query_error_with_its_offset(text, message, offset):
    with pytest.raises(QueryError) as caught:
        parse_query(text)
    assert str(caught.value) == f"{message} at offset {offset}"


def test_similar_keeps_the_rows_its_resolver_names_asking_once_per_text():
    asked = []

    def resolve(text):
        asked.append(text)
        return {"focal": {"a"}, "smooth": {"b", "zzz"}}.get(text, set())

    extra = _extra(similar=resolve)
    assert _verstrs('similar("focal")', extra) == ["a"]
    assert _verstrs('similar("focal") or similar("smooth") or similar("focal")', extra) == [
        "a", "b"]
    assert _verstrs('not similar("focal") and status = "succeeded"', extra) == ["c"]
    assert _verstrs('similar("nothing")', extra) == []
    assert asked == ["focal", "focal", "smooth", "focal", "nothing"]


def test_similar_without_a_resolver_is_a_query_error():
    with pytest.raises(QueryError, match="similar\\(\\) needs the persisted index"):
        filter_rows(ROWS, 'similar("focal")')


def test_a_query_without_similar_never_asks_the_resolver():
    def resolve(text):
        raise AssertionError("asked")

    assert _verstrs('status = "failed"', _extra(similar=resolve)) == ["b"]


@pytest.mark.parametrize("text", ['similar("x")', 'intent ~ "x"', 'keywords ~ "x"'])
def test_the_sql_backend_refuses_what_lean_rows_lack(text):
    with pytest.raises(QueryError, match="not supported by the SQL backend"):
        compile_sql(text)
