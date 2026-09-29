"""Custom x axes: ``define_metric(name, step_metric=...)`` and step joins.

A metric (exact name or glob) can declare another metric as its x axis; its
series is then keyed by that metric's value logged at the same step.
"""
import pytest

from vmn_exp.core.fold import fold_definitions, fold_log
from vmn_exp.core.log import metric_series
from vmn_exp.core.step_metric import (
    create_define_metric_entry,
    declared_step_metric,
    join_all,
    join_series,
    step_metrics,
)
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.sdk import reader
from vmn_exp.sdk.ranks import NoOpRun
from vmn_exp.sdk.run import Run

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"


def _m(step, ts, **values):
    return {"type": "metrics", "step": step, "timestamp": ts, "values": values}


# -- join semantics -------------------------------------------------------------


def test_join_keys_points_by_the_x_value_at_the_same_step():
    log = [
        _m(0, "t0", loss=1.0, epoch=0.0),
        _m(1, "t1", loss=0.5),  # no epoch at step 1: dropped
        _m(2, "t2", epoch=1.0),
        _m(2, "t3", loss=0.25),  # same step, a different call: joined
    ]
    joined = join_all(metric_series(log), "epoch")
    assert joined == {
        "loss": [
            {"step": 0, "ts": "t0", "value": 1.0, "x": 0.0},
            {"step": 2, "ts": "t3", "value": 0.25, "x": 1.0},
        ]
    }


def test_step_less_points_join_within_the_same_call_only():
    series = metric_series([
        {"type": "metrics", "timestamp": "t0", "values": {"acc": 0.1, "epoch": 1.0}},
        {"type": "metrics", "timestamp": "t1", "values": {"acc": 0.2}},
    ])
    assert join_series(series["acc"], series["epoch"]) == [
        {"step": None, "ts": "t0", "value": 0.1, "x": 1.0}
    ]


def test_non_finite_x_values_drop_the_point():
    series = metric_series([_m(0, "t0", loss=1.0, epoch=float("nan"))])
    assert join_series(series["loss"], series["epoch"]) == []


def test_join_on_a_missing_x_metric_is_empty():
    assert join_all(metric_series([_m(0, "t0", loss=1.0)]), "epoch") == {"loss": []}


# -- declarations ---------------------------------------------------------------


def test_definitions_fold_per_name_last_write_wins():
    log = [
        create_define_metric_entry("val_*", step_metric="epoch"),
        create_define_metric_entry("loss", step_metric="step2"),
        create_define_metric_entry("val_*", step_metric="global"),
    ]
    defs = fold_definitions(fold_log(log))
    assert defs["val_*"]["step_metric"] == "global"
    assert defs["loss"]["step_metric"] == "step2"


def test_define_metric_entry_keeps_extra_fields():
    entry = create_define_metric_entry("acc", step_metric="epoch", goal="max")
    assert entry["type"] == "define_metric"
    assert (entry["name"], entry["step_metric"], entry["goal"]) == ("acc", "epoch", "max")


@pytest.mark.parametrize("name,step", [("", "epoch"), (3, "epoch"), ("acc", 5)])
def test_define_metric_entry_rejects_bad_names(name, step):
    with pytest.raises(ValueError):
        create_define_metric_entry(name, step_metric=step)


def test_glob_declarations_match_and_exact_names_win():
    defs = {"val_*": {"step_metric": "epoch"}, "val_top": {"step_metric": "batch"}}
    assert declared_step_metric("val_loss", defs) == "epoch"
    assert declared_step_metric("val_top", defs) == "batch"
    assert declared_step_metric("loss", defs) is None


def test_a_metric_is_never_its_own_step_metric():
    assert declared_step_metric("epoch", {"*": {"step_metric": "epoch"}}) is None


def test_run_definitions_win_over_the_conf_schema():
    schema = {"val_*": {"goal": "min", "step_metric": "epoch"}, "acc": {"step_metric": "batch"}}
    defs = {"acc": {"step_metric": "epoch"}}
    assert step_metrics(["val_loss", "acc", "loss"], defs, schema) == {
        "val_loss": "epoch",
        "acc": "epoch",
    }


# -- SDK round trip -------------------------------------------------------------


@pytest.fixture
def storage(tmp_path):
    st = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "experiments"))
    st.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


def test_define_metric_round_trips_through_storage_and_reader(storage):
    run = Run(storage, APP, VERSTR, 60)
    run._open()
    run.define_metric("val_*", step_metric="epoch")
    for step in range(3):
        run.log_metrics({"val_loss": 1.0 / (step + 1), "epoch": step * 0.5}, step=step)
    run.log_metrics({"val_loss": 0.1}, step=9)  # no epoch at step 9
    run.finish()

    defs = fold_definitions(fold_log(storage.load_merged_log(APP, VERSTR)))
    assert defs == {"val_*": {"step_metric": "epoch"}}

    row = reader.get_run(APP, VERSTR, storage=storage)
    assert row["step_metrics"] == {"val_loss": "epoch"}
    assert len(row["series"]["val_loss"]) == 4  # the plain series is untouched

    joined = reader.get_run(APP, VERSTR, storage=storage, x="epoch")["series"]
    assert [p["x"] for p in joined["val_loss"]] == [0.0, 0.5, 1.0]
    assert "epoch" not in joined


def test_define_metric_rejects_a_bad_step_metric(storage):
    run = Run(storage, APP, VERSTR, 60)
    with pytest.raises(ValueError):
        run.define_metric("acc", step_metric=7)


def test_noop_run_accepts_define_metric():
    assert NoOpRun().define_metric("val_*", step_metric="epoch") is None
