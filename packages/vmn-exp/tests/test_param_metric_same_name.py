"""Plan 32 F8: a numeric param never overwrites a logged metric of the same
name. The logged metric holds ``metrics[name]``, the param stays in
``params``, and the row names the params that were also logged
(``logged_params``) so readers classify by the logged metric, not the name."""
from test_ui_diff_from_snapshot import _snap
from test_ui_diff_summary import _log_metrics, _log_params, _pair, _save_exp

from vmn_exp.core.fold import apply_entries, fold_row, new_fold
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.log import experiment_row
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.metric_time import us_to_iso
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.ui.readers import diffs as diff_reader

META = {"verstr": "0.0.1-dev.aaa.bbb", "timestamp": "2026-01-01T00:00:00Z"}
T0_US = 1_700_000_000_000_001


def _at(sec):
    return f"2026-01-01T00:00:{sec:02d}Z"


def _metric(sec, values):
    return {"timestamp": _at(sec), "type": "metrics", "values": values}


def _params(sec, values):
    return {"timestamp": _at(sec), "type": "params", "params": values}


def test_a_later_param_leaves_a_once_logged_metric_in_metrics():
    row = experiment_row(1, META, [_metric(1, {"acc": 0.9}), _params(2, {"acc": 3})])

    assert row["metrics"]["acc"] == 0.9
    assert row["params"]["acc"] == 3


def test_a_later_param_leaves_a_repeated_metric_at_its_last_value():
    log = [_metric(1, {"acc": 0.5}), _metric(2, {"acc": 0.9}), _params(3, {"acc": 3})]

    assert experiment_row(1, META, log)["metrics"]["acc"] == 0.9


def test_an_earlier_logged_metric_folded_after_a_later_param_still_wins():
    fold = new_fold()
    apply_entries(fold, "b", 0, [_params(5, {"acc": 3})])
    apply_entries(fold, "a", 0, [_metric(1, {"acc": 0.9})])

    row = fold_row(1, META, fold)

    assert row["metrics"]["acc"] == 0.9
    assert row["params"]["acc"] == 3


def test_a_param_never_logged_as_a_metric_still_folds_into_metrics():
    row = experiment_row(1, META, [_params(1, {"lr": 0.01}), _metric(2, {"loss": 0.5})])

    assert row["metrics"]["lr"] == 0.01
    assert "logged_params" not in row


def test_the_row_names_the_params_also_logged_as_metrics():
    log = [_params(1, {"acc": 3, "lr": 0.01}), _metric(2, {"acc": 0.9, "loss": 0.5})]

    assert experiment_row(1, META, log)["logged_params"] == ["acc"]


def _logged_once(storage, v):
    _log_params(storage, "myapp", v, {"acc": 3})
    _log_metrics(storage, "myapp", v, {"acc": 0.9}, ts="2025-01-01T00:00:01Z")


def _other(storage, v):
    _log_params(storage, "myapp", v, {"acc": 4})
    _log_metrics(storage, "myapp", v, {"acc": 0.7}, ts="2025-01-02T00:00:01Z")


def test_compare_keeps_a_once_logged_metric_sharing_a_param_name_a_metric(tmp_path):
    delta = _pair(LocalSnapshotStorage(str(tmp_path), area="runs"), _logged_once, _other)

    assert delta["acc"] == {"from": 0.9, "to": 0.7, "goal": None, "param": False}


def test_the_snapshot_compare_keeps_it_a_metric_too(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")
    v1, v2 = "1.0.0-dev.aaa.bbb", "1.0.0-dev.ccc.ddd"
    _save_exp(storage, "myapp", v1)
    _logged_once(storage, v1)
    _save_exp(storage, "myapp", v2, ts="2025-01-02T00:00:00Z")
    _other(storage, v2)

    delta = diff_reader.experiment_diff_from_snapshot(_snap(storage), v1, v2)["metrics_delta"]

    assert delta["acc"] == {"from": 0.9, "to": 0.7, "goal": None, "param": False}


def test_a_streamed_metric_keeps_its_place_from_a_later_param(tmp_path):
    storage, v = LocalSnapshotStorage(str(tmp_path), area="runs"), META["verstr"]
    storage.save("app", v, META, {})
    stream = MetricWriter(storage, "app", v, "a")
    stream.add("acc", 0.9, ts_us=T0_US)
    stream.add("acc", 0.8, ts_us=T0_US + 1000)
    stream.flush()
    later = {"timestamp": us_to_iso(T0_US + 5000), "type": "params", "params": {"acc": 3}}
    storage.append_log_entry("app", v, "a", later)

    row = ExperimentIndex(storage, "app").refresh().rows()[0]

    assert row["metrics"]["acc"] == 0.8
    assert row["params"]["acc"] == 3
