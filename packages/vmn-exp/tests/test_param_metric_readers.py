"""Plan 32 F8 in every reader: a metric the run logged under a param's name
is a metric — the board's common metrics, a run's objectives (similar runs,
baselines) and the run detail payload key on the logged metric, not the
shared name."""
from test_ui_diff_summary import _log_metrics, _log_params, _save_exp

from vmn_exp.core.fold import fold_log
from vmn_exp.core.index import snapshot_of_folds
from vmn_exp.core.log import experiment_row
from vmn_exp.core.similar_profile import objective_names
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.ui.leaderboard_facets import Facets
from vmn_exp.ui.readers.experiment_detail import experiment_detail

LOG = [
    {"timestamp": "2026-01-01T00:00:01Z", "type": "params", "params": {"acc": 3, "lr": 0.01}},
    {"timestamp": "2026-01-01T00:00:02Z", "type": "metrics", "values": {"acc": 0.9}},
]


def _meta(i):
    return {"verstr": f"0.0.1-dev.aaa.{i}", "timestamp": "2026-01-01T00:00:00Z"}


def test_the_boards_common_metrics_keep_a_logged_metric_sharing_a_param_name():
    snap = snapshot_of_folds("app", [(i, _meta(i), fold_log(LOG)) for i in (1, 2)])

    assert Facets().common_metrics(snap) == ["acc"]


def test_a_runs_objectives_keep_a_logged_metric_sharing_a_param_name():
    assert objective_names(experiment_row(1, _meta(1), LOG)) == frozenset({"acc"})


def test_the_run_detail_names_the_params_also_logged_as_metrics(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")
    verstr = "1.0.0-dev.aaa.bbb"
    _save_exp(storage, "myapp", verstr)
    _log_params(storage, "myapp", verstr, {"acc": 3, "lr": 0.01})
    _log_metrics(storage, "myapp", verstr, {"acc": 0.9}, ts="2025-01-01T00:00:01Z")

    detail, err = experiment_detail(storage, "myapp", verstr)

    assert err is None
    assert detail["logged_params"] == ["acc"]
    assert detail["metrics"]["acc"] == 0.9
