"""Plan 28 N2: the pivot heatmap's cells. Rows of the index snapshot crossed
by two group fields (rows x cols), each cell a count, the share of its runs
matching a query, or an aggregate of a metric, carrying the clause that
selects its runs; capped at 200 x 50 values, the most populous kept."""
import pytest
from leaderboard_group_rows import run, snapshot, v
from vmn_exp.core.query import QueryError, filter_rows
from vmn_exp.core.query_extra import lean_extra
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui.leaderboard_group_fields import NONE
from vmn_exp.ui.pivot import MAX_COLS, MAX_ROWS, pivot_spec
from vmn_exp.ui.pivot_cache import PivotCache

SCHEMA = {}


def _fleet():
    def trial(n, date, group, health="ok", loss=None, parent=1):
        return run(n, parent=parent, tags={"date": date, "group": group, "health": health},
                   metrics={} if loss is None else {"loss": loss})
    return snapshot([
        run(1, tags={"kind": "launch"}),
        trial(2, "d1", "g1", loss=1.0), trial(3, "d1", "g1", "unstable", loss=3.0),
        trial(4, "d1", "g2", loss=2.0), trial(5, "d2", "g1", "unstable"),
        trial(6, "d2", "g2", "unstable", loss=5.0), trial(7, "d2", "g2", loss=4.0),
        trial(8, "d2", "g2", loss=6.0),
        run(9, tags={"date": "d1"}),
    ])


def _pivot(snap, cache=None, **params):
    spec = pivot_spec(**{"rows": "tags.date", "cols": "tags.group", **params})
    return PivotCache(cache or lb.LeaderboardCache()).pivot(snap, SCHEMA, spec)


def _labels(headers):
    return [h["label"] for h in headers]


def _grid(body, what="n"):
    return [[cell and cell[what] for cell in line] for line in body["cells"]]


def test_counts_cross_two_fields():
    body = _pivot(_fleet(), scope=v(1))
    assert _labels(body["rows"]) == ["d1", "d2"]
    assert _labels(body["cols"]) == ["g1", "g2"]
    assert _grid(body) == [[2, 1], [1, 3]]
    assert [h["n"] for h in body["rows"]] == [3, 4]
    assert body["total"] == 7 and body["rows_total"] == 2 and body["cols_total"] == 2


def test_app_wide_pivot_has_a_none_value_last():
    body = _pivot(_fleet())
    assert _labels(body["rows"]) == ["d1", "d2", "(none)"]
    assert _labels(body["cols"]) == ["g1", "g2", "(none)"]
    assert body["rows"][-1]["key"] == NONE
    assert _grid(body) == [[2, 1, 1], [1, 3, None], [None, None, 1]]


def test_share_of_runs_matching_a_query():
    body = _pivot(_fleet(), scope=v(1), cell="share", match='tags.health = "unstable"')
    assert _grid(body, "hits") == [[1, 0], [1, 1]]
    assert _grid(body, "value") == [[0.5, 0.0], [1.0, pytest.approx(1 / 3)]]


def test_aggregate_of_a_metric():
    snap = _fleet()
    assert _grid(_pivot(snap, scope=v(1), cell="agg", metric="loss", agg="median"),
                 "value") == [[2.0, 2.0], [None, 5.0]]
    assert _grid(_pivot(snap, scope=v(1), cell="agg", metric="loss", agg="min"),
                 "value") == [[1.0, 2.0], [None, 4.0]]
    assert _grid(_pivot(snap, scope=v(1), cell="agg", metric="loss", agg="max"),
                 "value") == [[3.0, 2.0], [None, 6.0]]


def test_every_clause_selects_its_runs():
    snap = _fleet()
    body = _pivot(snap)
    every = list(snap.rows)

    def selected(clause):
        return sorted(r["verstr"] for r in filter_rows(every, clause, extra=lean_extra(snap)))

    assert selected(body["cells"][0][0]["clause"]) == [v(2), v(3)]
    assert body["cells"][1][2] is None
    assert selected(body["cells"][2][2]["clause"]) == [v(1)]
    assert selected(body["cells"][0][2]["clause"]) == [v(9)]
    assert selected(body["rows"][0]["clause"]) == [v(2), v(3), v(4), v(9)]
    assert selected(body["cols"][1]["clause"]) == [v(4), v(6), v(7), v(8)]


def test_filters_narrow_the_runs():
    snap = _fleet()
    assert _grid(_pivot(snap, scope=v(1), query="metrics.loss > 2")) == [[1, None], [None, 3]]
    assert _pivot(snap, scope=v(1), status="failed")["total"] == 0


def test_an_ancestor_field_is_a_pivot_field():
    snap = snapshot([
        run(1, params={"date": "d1"}), run(2, parent=1, tags={"group": "g1"}),
        run(3, parent=1, tags={"group": "g2"}), run(4, params={"date": "d2"}),
        run(5, parent=4, tags={"group": "g1"}),
    ])
    body = _pivot(snap, rows="up.params.date", query="depth > 0")
    assert _labels(body["rows"]) == ["d1", "d2"]
    assert _grid(body) == [[1, 1], [1, None]]
    assert body["rows"][0]["clause"] == 'up.params.date = "d1"'


def test_values_sort_numbers_before_text():
    snap = snapshot([run(i, params={"h": h}) for i, h in enumerate([10, 2, "x", 2.5], 1)])
    assert _labels(_pivot(snap, rows="params.h", cols="status")["rows"]) == ["2", "2.5", "10", "x"]


def test_capped_to_the_most_populous_values():
    specs = [run(i, tags={"date": f"d{i:03d}", "group": f"g{i % 60:02d}"}) for i in range(300)]
    specs += [run(1000 + i, tags={"date": "d299", "group": "g59"}) for i in range(3)]
    body = _pivot(snapshot(specs))
    assert len(body["rows"]) == MAX_ROWS == 200 and body["rows_total"] == 300
    assert len(body["cols"]) == MAX_COLS == 50 and body["cols_total"] == 60
    assert "d299" in _labels(body["rows"]) and "g59" in _labels(body["cols"])
    assert len(body["cells"]) == 200 and {len(line) for line in body["cells"]} == {50}
    assert _labels(body["rows"]) == sorted(_labels(body["rows"]))


@pytest.mark.parametrize("params", [
    dict(rows="bogus"), dict(cols="metrics.loss"), dict(cell="sum"),
    dict(cell="share"), dict(cell="agg"), dict(cell="agg", metric="loss", agg="p99"),
])
def test_bad_requests_are_value_errors(params):
    with pytest.raises(ValueError):
        pivot_spec(**{"rows": "tags.date", "cols": "tags.group", **params})


def test_a_bad_match_query_is_a_query_error():
    with pytest.raises(QueryError):
        _pivot(_fleet(), cell="share", match="tags.health ==")


def test_root_and_status_are_pivot_fields():
    body = _pivot(_fleet(), rows="root", cols="status")
    assert _labels(body["rows"]) == [v(1), "(none)"]
    assert [h["n"] for h in body["rows"]] == [7, 2]
    assert _labels(body["cols"]) == ["succeeded"]
    assert body["rows"][0]["clause"] == f'root = "{v(1)}"'
