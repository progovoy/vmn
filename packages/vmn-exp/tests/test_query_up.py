"""Plan 28 N1: ``up.<field>`` reads the nearest ancestor holding the field,
``up(<field> = <value>).<field>`` the nearest ancestor matching one equality."""
import pytest
from leaderboard_group_rows import run, snapshot, v
from vmn_exp.core.query import (
    QueryError,
    compile_query,
    filter_rows,
    parse_query,
    query_roots,
)
from vmn_exp.core.query_extra import lean_extra, reads_off_row
from vmn_exp.ui.query_sql import compile_sql


def _row(verstr, parent=None, params=None, tags=None, **kw):
    return {"verstr": verstr, "parent": parent, "metrics": {}, "params": params or {},
            "tags": tags or {}, **kw}


# launch <- date <- study <- trial <- pod; a second date with its own study and
# trial; an orphan whose parent was pruned.
ROWS = [
    _row("L", params={"mode": "wf"}, tags={"kind": "launch"}, name="launch-1"),
    _row("D1", "L", params={"trade_date": "2026-01-02"}, tags={"kind": "date"}),
    _row("S1", "D1", params={"group": "fx", "trade_date": "2026-01-02"},
         tags={"kind": "study"}, name="study-fx"),
    _row("T1", "S1", params={"lr": 0.1}, tags={"kind": "trial"}),
    _row("P1", "T1", tags={"kind": "pod/train"}),
    _row("D2", "L", params={"trade_date": "2026-01-03"}, tags={"kind": "date"}),
    _row("S2", "D2", params={"group": "rates"}, tags={"kind": "study"}),
    _row("T2", "S2", params={"lr": 0.2, "group": "own"}, tags={"kind": "trial"}),
    _row("O", "gone", params={"lr": 0.3}),
]


def _verstrs(text, rows=ROWS, extra=None):
    return [r["verstr"] for r in filter_rows(rows, text, extra=extra)]


def test_up_reads_the_nearest_ancestor_holding_the_key():
    assert _verstrs('up.params.trade_date = "2026-01-02"') == ["S1", "T1", "P1"]
    assert _verstrs('up.params.trade_date = "2026-01-03"') == ["S2", "T2"]
    assert _verstrs('up.params.mode = "wf"') == ["D1", "S1", "T1", "P1", "D2", "S2", "T2"]


def test_up_skips_the_run_itself():
    # T2 has its own group; up reads its study's.
    assert _verstrs('up.params.group = "rates"') == ["T2"]
    assert _verstrs('up.params.group = "own"') == []


def test_up_reads_tags_and_name():
    assert _verstrs('up.tags.kind = "trial"') == ["P1"]
    assert _verstrs('up.name = "study-fx"') == ["T1", "P1"]


def test_up_with_a_selector_reads_the_nearest_matching_ancestor():
    assert _verstrs('up(tags.kind = "study").params.group = "fx"') == ["T1", "P1"]
    assert _verstrs('up(tags.kind = "date").params.trade_date = "2026-01-03"') == ["S2", "T2"]
    # The matching ancestor lacks the key: missing, not the next one up.
    assert _verstrs('up(tags.kind = "study").params.trade_date = null') == [
        "L", "D1", "S1", "D2", "S2", "T2", "O"]


def test_up_selectors_take_params_and_name():
    assert _verstrs('up(params.group = "fx").name = "study-fx"') == ["T1", "P1"]
    assert _verstrs('up(name = "launch-1").params.mode in ("wf")') == [
        "D1", "S1", "T1", "P1", "D2", "S2", "T2"]


def test_up_works_with_every_operator_and_null():
    assert _verstrs('up.params.trade_date > "2026-01-02"') == ["S2", "T2"]
    assert _verstrs('up.params.trade_date ~ "01-03"') == ["S2", "T2"]
    assert _verstrs('up.params.mode = null') == ["L", "O"]
    assert _verstrs('not up.params.mode = "wf"') == ["L", "O"]
    assert _verstrs('up.params.trade_date = "2026-01-02" and params.lr > 0') == ["T1"]


def test_quoted_keys_after_up():
    rows = [_row("a", params={"odd/key": 1}), _row("b", "a")]
    assert _verstrs('up.params."odd/key" = 1', rows) == ["b"]
    assert _verstrs('up(tags.kind = "x").params."odd/key" = null', rows) == ["a", "b"]


def test_a_missing_ancestor_ends_the_chain():
    assert _verstrs('up.params.lr = 0.3') == []
    rows = [_row("c", "b"), _row("a", params={"k": 1})]  # b pruned, its parent unknown
    assert _verstrs("up.params.k = 1", rows) == []


def test_a_deep_chain_reaches_the_root():
    rows = [_row("n0", params={"k": "root"}, tags={"kind": "top"})]
    rows += [_row(f"n{i}", f"n{i - 1}") for i in range(1, 8)]
    assert _verstrs('up.params.k = "root"', rows) == [f"n{i}" for i in range(1, 8)]
    assert _verstrs('up(tags.kind = "top").params.k = "root"', rows) == [
        f"n{i}" for i in range(1, 8)]


def test_up_is_cycle_safe():
    rows = [_row("p", "q", params={"k": 1}), _row("q", "p")]
    assert _verstrs("up.params.k = 1", rows) == ["q"]
    assert _verstrs("up.params.missing = null", rows) == ["p", "q"]


def test_up_reads_from_the_resolver_when_given():
    calls = []

    def of(verstr):
        return lambda node: calls.append((verstr, node)) or "x"

    assert _verstrs('up.params.k = "x"', extra={"up": of}) == [r["verstr"] for r in ROWS]
    assert calls[0][1] == ("up", None, ("params", "k"))


@pytest.mark.parametrize("text", [
    "up = 1", "up.status = 'failed'", "up.metrics.loss < 1", "up.outputs.a.digest = 'x'",
    'up(tags.kind = "s") = 1', 'up(tags.kind = "s")', 'up(tags.kind ~ "s").name = "x"',
    'up(tags.kind = null).name = "x"', 'up(kind = "outer").name = "x"', "up().name = 'x'",
    'up(tags.kind = "s").up.name = "x"', 'up(tags.kind = "s" and name = "a").name = "x"',
    'up(tags.kind = "s".name = "x"',
])
def test_bad_up_fields_are_query_errors(text):
    with pytest.raises(QueryError):
        compile_query(text)


def test_the_ast_names_the_selector_and_the_field():
    assert parse_query('up.tags.k = "a"') == ("cmp", ("up", None, ("tags", "k")), "=", "a")
    assert parse_query('up(tags.kind = "study").params.g = 1') == (
        "cmp", ("up", (("tags", "kind"), "study"), ("params", "g")), "=", 1)


def test_up_reads_off_the_row():
    assert "up" in query_roots('up(tags.kind = "s").params.g = 1')
    assert "up" in query_roots('up.params."a/b" = 1')
    assert reads_off_row("up.params.g = 1")
    assert not reads_off_row("params.up = 1")


def test_the_sql_backend_refuses_up():
    with pytest.raises(QueryError):
        compile_sql('up.params.g = "a"')


def _tree_snapshot():
    return snapshot([
        run(1, params={"date": "d1"}, tags={"kind": "date"}),
        run(2, parent=1, params={"group": "g1"}, tags={"kind": "study"}),
        run(3, parent=2, params={"lr": 1}), run(4, parent=2, params={"lr": 2}),
        run(5, parent=1, params={"group": "g2"}, tags={"kind": "study"}),
        run(6, parent=5),
    ])


def test_snapshot_extra_resolves_through_the_snapshot_rows():
    snap = _tree_snapshot()
    rows = [snap.row(v(3)), snap.row(v(6))]  # the ancestors are not among the rows
    got = filter_rows(rows, 'up.params.date = "d1" and up(tags.kind = "study").params.group = "g2"',
                      extra=lean_extra(snap))
    assert [r["verstr"] for r in got] == [v(6)]


def test_each_ancestor_is_read_once_per_snapshot_and_field(monkeypatch):
    snap = _tree_snapshot()
    reads = []
    real = type(snap).row
    monkeypatch.setattr(type(snap), "row", lambda self, verstr: reads.append(verstr)
                        or real(self, verstr))
    for _ in range(3):
        filter_rows(snap.rows, 'up.params.date = "d1"', extra=lean_extra(snap))
    # Ancestors 1, 2 and 5: read once each, then the memo answers.
    assert sorted(set(reads)) == [v(1), v(2), v(5)]
    assert len(reads) == 3


def test_the_memo_is_per_snapshot():
    from vmn_exp.core import query_up

    first, second = _tree_snapshot(), _tree_snapshot()
    assert query_up.ancestor_fields(first) is query_up.ancestor_fields(first)
    assert query_up.ancestor_fields(first) is not query_up.ancestor_fields(second)


def test_the_memo_keeps_no_cycle_through_the_snapshot():
    import gc
    import weakref

    snap = _tree_snapshot()
    filter_rows(snap.rows, 'up.params.date = "d1"', extra=lean_extra(snap))
    ref = weakref.ref(snap)
    gc.disable()
    try:
        del snap
        assert ref() is None  # freed by its refcount, no collection needed
    finally:
        gc.enable()
