"""``first`` and ``mean`` summaries: the fold keeps them order-free.

``first`` is the earliest value by the fold key (timestamp, writer,
position), whatever order the writers are folded in; ``mean`` is the mean
of a metric's finite values.
"""
import json
import sqlite3

import pytest

from vmn_exp.core.fold import apply_entries, fold_log, fold_row, new_fold
from vmn_exp.core.index_store import SCHEMA_VERSION, IndexStore
from vmn_exp.core.log import experiment_row
from vmn_exp.core.metric_summary import summary_fields

META = {"verstr": "0.0.1-dev.aaa.bbb", "timestamp": "2026-01-01T00:00:00Z"}
NAN, INF = float("nan"), float("inf")


def _m(sec, values):
    return {"timestamp": f"2026-01-01T00:00:{sec:02d}Z", "type": "metrics",
            "values": values}


def _row(log, schema=None):
    return experiment_row(1, META, log, schema=schema)


def test_mean_summary_ranks_on_the_mean_of_finite_values():
    log = [_m(i, {"loss": v}) for i, v in enumerate([1.0, NAN, 3.0, INF, 5.0])]
    row = _row(log, {"loss": {"summary": "mean"}})
    assert row["metrics"]["loss"] == pytest.approx(3.0)


def test_mean_without_a_finite_value_falls_back_to_the_last():
    log = [_m(0, {"loss": NAN}), _m(1, {"loss": INF})]
    row = _row(log, {"loss": {"summary": "mean"}})
    assert row["metrics"]["loss"] == INF
    assert row["metric_summary"]["loss"]["mean"] is None


def test_first_summary_is_the_earliest_by_timestamp_across_writers():
    late = [_m(2, {"loss": 0.5}), _m(3, {"loss": 0.4})]
    early = [_m(1, {"loss": 0.9})]
    for order in ((("b", late), ("a", early)), (("a", early), ("b", late))):
        fold = new_fold()
        for writer, entries in order:
            apply_entries(fold, writer, 0, entries)
        row = fold_row(1, META, fold, schema={"loss": {"summary": "first"}})
        assert row["metrics"]["loss"] == 0.9
        assert row["metric_summary"]["loss"]["first"] == 0.9


def test_first_ignores_a_same_named_param():
    log = [
        _m(1, {"lr": 1.0}),
        {"timestamp": "2026-01-01T00:00:02Z", "type": "params", "params": {"lr": 0.7}},
        _m(3, {"lr": 2.0}),
    ]
    row = _row(log, {"lr": {"summary": "first"}})
    assert row["metric_summary"]["lr"]["first"] == 1.0
    assert row["metrics"]["lr"] == 1.0


def test_metric_summary_payload_has_first_and_mean():
    log = [_m(i, {"loss": v}) for i, v in enumerate([1.0, 0.4, 0.9])]
    summary = _row(log)["metric_summary"]["loss"]
    assert summary == {"last": 0.9, "min": 0.4, "max": 1.0, "first": 1.0,
                       "mean": pytest.approx(2.3 / 3)}


def test_summary_none_is_rejected():
    with pytest.raises(ValueError):
        summary_fields(summary="none")
    assert summary_fields(summary="first") == {"summary": "first"}
    assert summary_fields(summary="mean") == {"summary": "mean"}


def test_repeated_metric_extra_state_is_bounded():
    def fold_of(n):
        return fold_log([_m(i % 60, {"loss": float(i)}) for i in range(n)])

    small, big = fold_of(10), fold_of(1000)
    assert len(big["extrema"]["loss"]) == len(small["extrema"]["loss"])
    assert list(big.get("firsts", {})) == ["loss"]
    assert len(json.dumps(big)) - len(json.dumps(small)) < 64


def test_index_schema_version_bumped_refolds_old_records(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    IndexStore(path).save("app", {"k": {"verstr": "0.0.1"}}, set(), {})
    conn = sqlite3.connect(path)
    conn.execute("UPDATE exp_index_meta SET v = 'exp-index-8' WHERE k = 'schema'")
    conn.commit()
    conn.close()
    assert SCHEMA_VERSION != "exp-index-8"
    assert IndexStore(path).load("app") == {}
