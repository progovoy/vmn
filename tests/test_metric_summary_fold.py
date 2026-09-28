"""Best-value metric summaries: a row ranks a metric by its summary policy.

The fold keeps each metric's last, min and max; ``row["metrics"][name]`` is
the value the metric's summary policy picks (``min``/``max``/``last``), taken
from the run's own ``define_metric`` entries, else the app's metrics schema,
else ``goal`` (min -> min, max -> max), else ``last``.
"""
import math
import random

import pytest

from vmn_exp.core.fold import apply_entries, fold_row, new_fold
from vmn_exp.core.log import experiment_row, sort_by_metric
from vmn_exp.core.metric_summary import define_metric_entry
from vmn_exp.core.query import filter_rows

META = {"verstr": "0.0.1-dev.aaa.bbb", "timestamp": "2026-01-01T00:00:00Z"}
NAN, INF = float("nan"), float("inf")


def _m(sec, values, step=None):
    entry = {"timestamp": f"2026-01-01T00:00:{sec:02d}Z", "type": "metrics",
             "values": values}
    if step is not None:
        entry["step"] = step
    return entry


def _losses(*values):
    return [_m(i, {"loss": v}, step=i) for i, v in enumerate(values)]


OVERFIT = _losses(1.0, 0.4, 0.9)  # loss goes down, then back up


def _row(log, schema=None):
    return experiment_row(1, META, log, schema=schema)


def test_without_a_policy_the_last_value_wins():
    assert _row(OVERFIT)["metrics"]["loss"] == 0.9


def test_goal_min_ranks_on_the_minimum():
    assert _row(OVERFIT, {"loss": {"goal": "min"}})["metrics"]["loss"] == 0.4


def test_goal_max_ranks_on_the_maximum():
    assert _row(OVERFIT, {"loss": {"goal": "max"}})["metrics"]["loss"] == 1.0


def test_summary_last_overrides_the_goal():
    schema = {"loss": {"goal": "min", "summary": "last"}}
    assert _row(OVERFIT, schema)["metrics"]["loss"] == 0.9


def test_summary_min_without_a_goal():
    assert _row(OVERFIT, {"loss": {"summary": "min"}})["metrics"]["loss"] == 0.4


def test_the_full_summary_is_exposed():
    row = _row(OVERFIT, {"loss": {"goal": "min"}})
    assert row["metric_summary"]["loss"] == {"last": 0.9, "min": 0.4, "max": 1.0}


def test_a_single_value_metric_carries_no_summary():
    row = _row(_losses(0.5))
    assert row["metrics"]["loss"] == 0.5
    assert "loss" not in row["metric_summary"]


def test_non_finite_values_are_excluded_from_min_and_max():
    row = _row(_losses(NAN, 0.3, INF, 0.2, NAN), {"loss": {"goal": "min"}})
    assert row["metrics"]["loss"] == 0.2
    summary = row["metric_summary"]["loss"]
    assert (summary["min"], summary["max"]) == (0.2, 0.3)
    assert math.isnan(summary["last"])


def test_an_all_nan_metric_keeps_its_last_value_and_sorts_last():
    schema = {"loss": {"goal": "min"}}
    nan_row = _row(_losses(NAN, NAN), schema)
    assert math.isnan(nan_row["metrics"]["loss"])
    assert nan_row["metric_summary"]["loss"]["min"] is None
    good = dict(_row(OVERFIT, schema), verstr="good")
    assert sort_by_metric([nan_row, good], schema, sort="loss")[0] is good


def test_the_runs_own_definition_is_recorded_in_the_log():
    log = [define_metric_entry("loss", summary="min")] + OVERFIT
    assert _row(log)["metrics"]["loss"] == 0.4


def test_the_runs_goal_derives_its_summary():
    log = [define_metric_entry("acc", goal="max")] + [
        _m(i, {"acc": v}) for i, v in enumerate((0.7, 0.9, 0.8))
    ]
    assert _row(log)["metrics"]["acc"] == 0.9


def test_the_runs_definition_beats_the_app_schema():
    log = [define_metric_entry("loss", summary="last")] + OVERFIT
    assert _row(log, {"loss": {"goal": "min"}})["metrics"]["loss"] == 0.9


def test_a_later_definition_wins():
    log = [define_metric_entry("loss", summary="min")] + OVERFIT
    log.append(dict(define_metric_entry("loss", summary="max"),
                    timestamp="2026-01-01T00:01:00Z"))
    assert _row(log)["metrics"]["loss"] == 1.0


@pytest.mark.parametrize("kwargs", [{"summary": "mean"}, {"goal": "up"}, {}])
def test_define_metric_entry_rejects_bad_policies(kwargs):
    with pytest.raises(ValueError):
        define_metric_entry("loss", **kwargs)


def test_numeric_params_still_fold_into_metrics():
    log = [{"timestamp": "2026-01-01T00:00:00Z", "type": "create",
            "params": {"lr": 0.1}}] + OVERFIT
    row = _row(log, {"lr": {"goal": "min"}})
    assert row["metrics"]["lr"] == 0.1


def test_query_and_sort_see_the_summary_value():
    schema = {"loss": {"goal": "min"}}
    overfit = dict(_row(OVERFIT, schema), verstr="overfit")  # best 0.4, last 0.9
    steady = dict(_row(_losses(0.8, 0.6), schema), verstr="steady")  # best 0.6
    ranked = sort_by_metric([steady, overfit], schema, sort="loss")
    assert [r["verstr"] for r in ranked] == ["overfit", "steady"]
    assert [r["verstr"] for r in filter_rows([overfit, steady], "metrics.loss < 0.5")] == [
        "overfit"
    ]


def _random_log(rng):
    entries = []
    for i in range(rng.randint(1, 25)):
        ts = f"2026-01-01T00:00:{rng.randint(0, 9):02d}Z"
        if rng.random() < 0.15:
            entry = define_metric_entry(
                rng.choice(["loss", "acc"]), summary=rng.choice(["min", "max", "last"])
            )
        else:
            names = rng.sample(["loss", "acc"], rng.randint(1, 2))
            entry = {"type": "metrics",
                     "values": {n: rng.choice([rng.random(), NAN, INF, 3]) for n in names}}
        entry["timestamp"] = ts
        entries.append(entry)
    return entries


def _same(a, b):
    if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return a == b


@pytest.mark.parametrize("seed", range(40))
def test_incremental_chunks_fold_to_the_same_summaries(seed):
    rng = random.Random(seed)
    logs = {w: _random_log(rng) for w in ("a", "b")}
    merged = sorted(logs["a"] + logs["b"], key=lambda e: e["timestamp"])
    schema = {"loss": {"goal": "min"}, "acc": {"goal": "max"}}

    fold = new_fold()
    for writer, entries in logs.items():
        cut = rng.randint(0, len(entries))
        apply_entries(fold, writer, 0, entries[:cut])
        apply_entries(fold, writer, cut, entries[cut:])
    got = fold_row(1, META, fold, schema=schema)
    want = experiment_row(1, META, merged, schema=schema)
    assert _same(got["metrics"], want["metrics"]), (got["metrics"], want["metrics"])
    assert _same(got["metric_summary"], want["metric_summary"])
