"""Plan 28 N2: the ``pivot`` report panel's spec: rows x cols of two group
fields, a cell of ``count`` (default), ``share`` (needs ``match``, a query)
or ``agg`` (needs ``metric``; ``agg`` one of the group aggregates)."""
import pytest

from vmn_exp.core.panel_spec import validate_panel

LIVE = {"query": 'tags.kind = "trial"'}


def _pivot(**extra):
    return {"v": 1, "id": "p1", "type": "pivot", "app": "trainer", "runs": LIVE,
            "rows": "tags.date", "cols": "root", **extra}


@pytest.mark.parametrize("extra", [
    {}, {"cell": "count"}, {"cell": "share", "match": "status = \"failed\""},
    {"cell": "agg", "metric": "loss"}, {"cell": "agg", "metric": "loss", "agg": "median"},
    {"scope": "0.0.1-dev.abc"},
])
def test_valid_pivots(extra):
    result = validate_panel(_pivot(**extra))
    assert result.ok, result.error


@pytest.mark.parametrize("extra, message", [
    ({"cell": "sum"}, "cell"),
    ({"cell": "share"}, "match"),
    ({"cell": "agg"}, "metric"),
    ({"cell": "agg", "metric": "loss", "agg": "p99"}, "agg"),
    ({"cell": "share", "match": "status = ="}, "match"),
])
def test_invalid_pivots(extra, message):
    result = validate_panel(_pivot(**extra))
    assert not result.ok and message in result.error


def test_pinned_runs_are_fine():
    assert validate_panel({**_pivot(), "runs": {"verstrs": ["a", "b"]}}).ok
