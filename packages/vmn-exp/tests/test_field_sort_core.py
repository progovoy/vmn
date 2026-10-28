"""Plan 28 FS + N4: ``queue_sec`` on every annotated row, and sorting by
any row field, ``tags.<k>`` or ``params.<k>`` (missing values last either
way, storage order breaking ties)."""
import datetime

import pytest
from vmn_exp.core import status as st
from vmn_exp.core.field_sort import field_sort
from vmn_exp.core.log import sort_by_metric
from vmn_exp.core.query import QueryError, filter_rows
from vmn_exp.core.tree import annotate_rows

NOW = datetime.datetime(2026, 9, 21, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _ago(seconds):
    return (NOW - datetime.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _row(verstr, created=None):
    return {"verstr": verstr, "idx": 1, "timestamp": created, "metrics": {}, "params": {}}


def _annotated(rows, states):
    return {r["verstr"]: r for r in annotate_rows(rows, states, now=NOW)}


def test_queue_sec_is_start_minus_creation():
    rows = [_row("a", _ago(900)), _row("b", _ago(900)), _row("c", None), _row("d", _ago(10))]
    states = {
        "a": {"state": "finished", "exit_code": 0, "started_at": _ago(600),
              "finished_at": _ago(60)},
        "b": None,  # still waiting
        "c": {"state": "running", "started_at": _ago(30), "heartbeat": _ago(1)},
        "d": {"state": "running", "started_at": _ago(20), "heartbeat": _ago(1)},  # clock skew
    }
    got = _annotated(rows, states)
    assert got["a"]["queue_sec"] == 300
    assert got["b"]["queue_sec"] is None  # not started: no queue time yet
    assert got["c"]["queue_sec"] is None  # no creation time
    assert got["d"]["queue_sec"] == 0  # never negative


def test_queue_sec_ignores_unparsable_stamps():
    assert st.queue_sec("yesterday", _ago(5)) is None
    assert st.queue_sec(_ago(5), None) is None


def test_the_new_fields_are_query_fields():
    rows = [dict(_row("a"), queue_sec=400.0, duration_ratio=3.5),
            dict(_row("b"), queue_sec=10.0, duration_ratio=0.9), _row("c")]
    assert [r["verstr"] for r in filter_rows(rows, "queue_sec > 60")] == ["a"]
    assert [r["verstr"] for r in filter_rows(rows, "duration_ratio > 3")] == ["a"]
    assert [r["verstr"] for r in filter_rows(rows, "duration_ratio = null")] == ["c"]
    with pytest.raises(QueryError):
        filter_rows(rows, "queue_secs > 1")


@pytest.mark.parametrize("sort, path", [
    ("duration_sec", ("duration_sec",)), ("queue_sec", ("queue_sec",)),
    ("duration_ratio", ("duration_ratio",)), ("status", ("status",)),
    ("tags.kind", ("tags", "kind")), ("params.lr.base", ("params", "lr.base")),
])
def test_field_sorts_are_recognized(sort, path):
    assert field_sort(sort).path == path


@pytest.mark.parametrize("sort", [None, "", "loss", "timestamp", "started_at", "idx",
                                  "tags.", "metrics.loss", "intent", "job:best"])
def test_other_sorts_are_not_field_sorts(sort):
    assert field_sort(sort) is None


def _sorted(rows, sort, descending=None):
    return [r["verstr"] for r in sort_by_metric(rows, {}, sort=sort, descending=descending)]


def test_numeric_field_sort_keeps_missing_last_both_ways():
    rows = [{"verstr": v, "idx": i, "metrics": {}, "duration_sec": d}
            for i, (v, d) in enumerate([("a", 30), ("b", None), ("c", 5), ("d", 30), ("e", 900)])]
    rows.append({"verstr": "f", "idx": 9, "metrics": {}})
    assert _sorted(rows, "duration_sec") == ["c", "a", "d", "e", "b", "f"]
    assert _sorted(rows, "duration_sec", descending=True) == ["e", "a", "d", "c", "b", "f"]


def test_tag_sort_is_string_order():
    rows = [{"verstr": v, "idx": 1, "metrics": {}, "tags": tags} for v, tags in [
        ("a", {"kind": "trial"}), ("b", {}), ("c", {"kind": "refit"}), ("d", None),
        ("e", {"kind": "assembler"})]]
    assert _sorted(rows, "tags.kind") == ["e", "c", "a", "b", "d"]
    assert _sorted(rows, "tags.kind", descending=True) == ["a", "c", "e", "b", "d"]


def test_param_sort_orders_numbers_before_strings_and_drops_containers():
    params = [("a", "x"), ("b", 3), ("c", [1]), ("d", 0.5), ("e", True), ("f", "a"),
              ("g", float("nan"))]
    rows = [{"verstr": v, "idx": 1, "metrics": {}, "params": {"p": p}} for v, p in params]
    assert _sorted(rows, "params.p") == ["d", "e", "b", "f", "a", "c", "g"]
    assert _sorted(rows, "params.p", descending=True) == ["a", "f", "b", "e", "d", "c", "g"]
