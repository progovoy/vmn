"""Plan 23 S2: ``under("<v>")`` is true for the rows in v's subtree (v itself
excluded), and ``root``/``failure_sig`` are query fields."""
import pytest
from vmn_exp.core.query import QueryError, compile_query, filter_rows, query_roots
from vmn_exp.ui.query_sql import compile_sql


def _row(verstr, parent=None, **kw):
    return {"verstr": verstr, "parent": parent, "metrics": {}, "params": {}, **kw}


# a <- b <- c, a <- d, e alone, f's parent is pruned
ROWS = [_row("a"), _row("b", "a"), _row("c", "b"), _row("d", "a", status="failed"),
        _row("e"), _row("f", "gone")]


def _verstrs(text, rows=ROWS, extra=None):
    return [r["verstr"] for r in filter_rows(rows, text, extra=extra)]


def test_under_is_the_subtree_without_the_run_itself():
    assert _verstrs('under("a")') == ["b", "c", "d"]
    assert _verstrs("under('b')") == ["c"]
    assert _verstrs('under("e")') == []
    assert _verstrs('under("gone")') == ["f"]


def test_under_combines_with_the_rest_of_the_language():
    assert _verstrs('under("a") and status = "failed"') == ["d"]
    assert _verstrs('not under("a")') == ["a", "e", "f"]
    assert _verstrs('under("b") or under("e") or verstr = "e"') == ["c", "e"]


def test_under_reads_ancestry_from_the_resolver_when_given():
    extra = {"ancestors": lambda verstr: ("x",) if verstr == "e" else ()}
    assert _verstrs('under("x")', extra=extra) == ["e"]


def test_under_is_cycle_safe():
    rows = [_row("p", "q"), _row("q", "p")]
    assert _verstrs('under("p")', rows) == ["q"]


def test_under_reads_ancestors():
    assert "ancestors" in query_roots('under("a") and idx > 1')


@pytest.mark.parametrize("text", ['under(1)', 'under("a"', "under", 'under("a", "b")',
                                  'under = "a"'])
def test_bad_under_is_a_query_error(text):
    with pytest.raises(QueryError):
        compile_query(text)


def test_root_and_failure_sig_are_fields():
    rows = [_row("a", root=None), _row("b", root="a", failure_sig="failed | exit=1")]
    assert _verstrs('root = "a"', rows) == ["b"]
    assert _verstrs('failure_sig ~ "exit=1"', rows) == ["b"]


def test_the_sql_backend_refuses_under():
    with pytest.raises(QueryError):
        compile_sql('under("a")')
