"""The pure log-folding core shared by the CLI, the ui readers and the SDK."""
import pytest

from version_stamp.core.experiment_log import (
    effective_params,
    entry_params,
    experiment_row,
    filter_by_status,
    last_metric_at,
    latest_metrics,
    list_artifacts,
    load_log,
    metric_series,
    metric_sort_descending,
    sort_by_metric,
)


def _metrics(values, step=None, ts="2026-09-21T12:00:00Z"):
    return {"type": "metrics", "timestamp": ts, "values": values, "step": step}


# ---------------------------------------------------------------------------
# params
# ---------------------------------------------------------------------------


def test_entry_params_reads_create_and_params_entries():
    assert entry_params({"type": "create", "params": {"lr": 0.01}}) == {"lr": 0.01}
    assert entry_params({"type": "params", "params": {"lr": 0.02}}) == {"lr": 0.02}


def test_entry_params_ignores_other_entry_types():
    assert entry_params(_metrics({"loss": 1.0})) == {}
    assert entry_params({"type": "create"}) == {}


def test_effective_params_folds_later_params_over_create():
    log = [
        {"type": "create", "params": {"lr": 0.01, "optimizer": "adam"}},
        {"type": "params", "params": {"lr": 0.05}},
    ]
    assert effective_params(log) == {"lr": 0.05, "optimizer": "adam"}


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def test_latest_metrics_keeps_the_last_value_of_each_metric():
    log = [_metrics({"loss": 1.0, "acc": 0.1}), _metrics({"loss": 0.3})]
    assert latest_metrics(log) == {"loss": 0.3, "acc": 0.1}


def test_latest_metrics_folds_numeric_params_and_skips_unparsable_ones():
    log = [{"type": "create", "params": {"lr": "0.01", "optimizer": "adam"}}]
    assert latest_metrics(log) == {"lr": 0.01}


def test_metric_series_yields_points_in_log_order():
    log = [
        _metrics({"loss": 1.0}, step=1, ts="t1"),
        _metrics({"loss": 0.3}, step=2, ts="t2"),
    ]
    assert metric_series(log) == {
        "loss": [
            {"step": 1, "ts": "t1", "value": 1.0},
            {"step": 2, "ts": "t2", "value": 0.3},
        ]
    }


def test_last_metric_at_returns_the_newest_metrics_timestamp():
    log = [_metrics({"a": 1}, ts="t1"), _metrics({"a": 2}, ts="t2"), {"type": "note"}]
    assert last_metric_at(log) == "t2"
    assert last_metric_at([{"type": "note"}]) is None


@pytest.mark.parametrize(
    "schema, expected",
    [
        ({}, True),
        ({"loss": {"goal": "min"}}, False),
        ({"loss": {"goal": "max"}}, True),
    ],
)
def test_metric_sort_descending_follows_the_goal(schema, expected):
    assert metric_sort_descending(schema, "loss") is expected


def test_metric_sort_descending_warns_and_falls_back_on_a_bad_goal():
    from version_stamp.core.logging import init_stamp_logger

    init_stamp_logger(supress_stdout=True)
    assert metric_sort_descending({"loss": {"goal": "nonsense"}}, "loss") is True


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------


def test_experiment_row_carries_metadata_metrics_and_last_metric_at():
    meta = {"verstr": "0.0.1", "timestamp": "t0", "note": "n", "parent": "0.0.0"}
    row = experiment_row(3, meta, [_metrics({"loss": 0.5}, ts="t9")])
    assert row["idx"] == 3
    assert row["verstr"] == "0.0.1"
    assert row["code_verstr"] == "0.0.1"  # defaults to verstr
    assert row["note"] == "n"
    assert row["parent"] == "0.0.0"
    assert row["metrics"] == {"loss": 0.5}
    assert row["last_metric_at"] == "t9"


def test_experiment_row_carries_params_verbatim():
    """Params reach the row untouched — the metrics fold cannot carry a string."""
    log = [{"type": "create", "params": {"lr": 0.01, "model": "xgb", "cache": True}}]
    row = experiment_row(1, {"verstr": "0.0.1"}, log)
    assert row["params"] == {"lr": 0.01, "model": "xgb", "cache": True}
    assert row["params"]["cache"] is True


def test_experiment_row_params_keeps_a_numeric_param_in_metrics_too():
    log = [{"type": "create", "params": {"lr": "0.01"}}]
    row = experiment_row(1, {"verstr": "0.0.1"}, log)
    assert row["params"] == {"lr": "0.01"}
    assert row["metrics"] == {"lr": 0.01}


def test_experiment_row_params_folds_a_mid_run_params_entry_over_create():
    log = [
        {"type": "create", "params": {"lr": 0.01, "model": "xgb"}},
        {"type": "params", "params": {"lr": 0.05}},
    ]
    row = experiment_row(1, {"verstr": "0.0.1"}, log)
    assert row["params"] == {"lr": 0.05, "model": "xgb"}


def test_experiment_row_params_is_an_empty_dict_without_params():
    row = experiment_row(1, {"verstr": "0.0.1"}, [_metrics({"loss": 0.5})])
    assert row["params"] == {}


def test_filter_by_status_takes_a_list_or_a_comma_separated_string():
    rows = [{"status": "failed"}, {"status": "succeeded"}, {"status": "running"}]
    assert filter_by_status(rows, "failed, running") == [rows[0], rows[2]]
    assert filter_by_status(rows, ["succeeded"]) == [rows[1]]
    assert filter_by_status(rows, None) == rows


def _rows(*pairs):
    return [{"verstr": v, "metrics": m} for v, m in pairs]


def test_sort_by_metric_uses_the_primary_metric_and_its_goal():
    rows = _rows(("a", {"loss": 0.5}), ("b", {"loss": 0.1}))
    schema = {"loss": {"primary": True, "goal": "min"}}
    assert [r["verstr"] for r in sort_by_metric(rows, schema)] == ["b", "a"]


def test_sort_by_metric_sorts_an_off_schema_metric_ascending():
    rows = _rows(("a", {"acc": 0.9}), ("b", {"acc": 0.1}))
    assert [r["verstr"] for r in sort_by_metric(rows, {}, sort="acc")] == ["b", "a"]


def test_sort_by_metric_puts_rows_missing_the_metric_last():
    rows = _rows(("a", {}), ("b", {"acc": 0.1}))
    assert [r["verstr"] for r in sort_by_metric(rows, {}, sort="acc")] == ["b", "a"]


def test_sort_by_metric_leaves_rows_alone_when_the_metric_is_unknown():
    rows = _rows(("a", {"loss": 1.0}), ("b", {"loss": 0.1}))
    assert sort_by_metric(rows, {}, sort="nope") == rows
    assert sort_by_metric(rows, {}) == rows


# ---------------------------------------------------------------------------
# storage-backed reads
# ---------------------------------------------------------------------------


class _FakeStorage:
    def __init__(self, log=None, art_dir=None):
        self._log = log or []
        self._art_dir = art_dir

    def load_merged_log(self, app_name, verstr):
        return self._log

    def list_artifact_files(self, app_name, verstr):
        return self._art_dir


def test_load_log_delegates_to_the_storage_backend():
    log = [_metrics({"loss": 1.0})]
    assert load_log(_FakeStorage(log), "app", "0.0.1") == log


def test_list_artifacts_reports_name_and_size_of_each_file(tmp_path):
    (tmp_path / "model.bin").write_text("weights")
    (tmp_path / "sub").mkdir()
    artifacts = list_artifacts(_FakeStorage(art_dir=str(tmp_path)), "app", "0.0.1")
    assert artifacts == [{"name": "model.bin", "size": len("weights")}]


def test_list_artifacts_is_empty_without_an_artifact_dir():
    assert list_artifacts(_FakeStorage(), "app", "0.0.1") == []
    assert list_artifacts(_FakeStorage(art_dir="/nope/nope"), "app", "0.0.1") == []


def test_core_does_not_import_upward():
    """core/ may never import cli/, ui/ or exp/ — that is the layering rule."""
    import pathlib

    core = pathlib.Path(__file__).resolve().parent.parent / "version_stamp" / "core"
    offenders = [
        path.name
        for path in core.glob("*.py")
        for line in path.read_text().splitlines()
        if line.startswith(("import ", "from "))
        and any(
            f"version_stamp.{pkg}" in line for pkg in ("cli", "ui", "exp", "stamping")
        )
    ]
    assert offenders == []
