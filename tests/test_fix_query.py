"""Query-language fixes: scientific notation, bounded nesting, list contains."""
import pytest

from version_stamp.core.experiment_query import QueryError, compile_query, filter_rows


def _row(verstr, **kw):
    row = {"verstr": verstr, "metrics": {}, "params": {}, "status": "succeeded"}
    row.update(kw)
    return row


ROWS = [
    _row("a", params={"lr": 0.0001}, metrics={"x": 3000.0, "d": -0.01},
         command=["python", "train.py"], children=["kid.r1"],
         user_meta={"team": "Vision"}),
    _row("b", params={"lr": 0.01}, metrics={"x": 10.0, "d": 0.5},
         command=["bash", "eval.sh"], children=[], user_meta={"team": "nlp"}),
]


def _verstrs(text, rows=ROWS):
    return [r["verstr"] for r in filter_rows(rows, text)]


# ---- scientific notation ---------------------------------------------------


def test_scientific_notation_literal():
    assert _verstrs("params.lr = 1e-4") == ["a"]


def test_scientific_notation_with_uppercase_and_sign():
    assert _verstrs("metrics.x > 2.5E+3") == ["a"]


def test_negative_scientific_notation():
    assert _verstrs("metrics.d < -1e-3") == ["a"]


@pytest.mark.parametrize("text", ["params.lr = 1e", "params.lr = 1e+", "metrics.x > 1e999x"])
def test_malformed_exponent_is_a_query_error(text):
    with pytest.raises(QueryError):
        compile_query(text)


def test_plain_integer_literal_still_an_int():
    assert _verstrs("metrics.x = 10") == ["b"]


# ---- nesting limits --------------------------------------------------------


def test_deep_parentheses_raise_query_error_not_recursion_error():
    text = "(" * 5000 + 'verstr = "a"' + ")" * 5000
    with pytest.raises(QueryError):
        compile_query(text)


def test_deep_not_chain_raises_query_error():
    with pytest.raises(QueryError):
        compile_query("not " * 5000 + 'verstr = "a"')


def test_moderate_nesting_still_works():
    text = "(" * 20 + 'verstr = "a"' + ")" * 20
    assert _verstrs(text) == ["a"]


def test_very_long_and_chain_evaluates():
    text = 'verstr = "a"' + ' and verstr = "a"' * 20000
    assert _verstrs(text) == ["a"]


def test_very_long_or_chain_evaluates():
    text = 'verstr = "zz"' + ' or verstr = "zz"' * 20000 + ' or verstr = "b"'
    assert _verstrs(text) == ["b"]


# ---- contains on list / dict fields ----------------------------------------


def test_contains_matches_any_list_element():
    assert _verstrs('command ~ "train"') == ["a"]


def test_contains_on_list_is_case_insensitive():
    assert _verstrs('command ~ "EVAL"') == ["b"]


def test_negated_contains_on_list():
    assert _verstrs('command !~ "train"') == ["b"]


def test_contains_on_children():
    assert _verstrs('children ~ "kid"') == ["a"]


def test_contains_matches_any_dict_value():
    assert _verstrs('user_meta ~ "vision"') == ["a"]


def test_contains_on_empty_list_is_false():
    assert _verstrs('children ~ "anything"') == []
