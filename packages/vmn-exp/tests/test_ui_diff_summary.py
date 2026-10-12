#!/usr/bin/env python3
"""Tests for the diff endpoint returning summary-policy values, goal and param flags."""
import pytest

from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.ui.readers import diffs as diff_reader


def _save_exp(storage, app, verstr, ts="2025-01-01T00:00:00Z"):
    storage.save(
        app,
        verstr,
        {
            "verstr": verstr,
            "app_name": app,
            "timestamp": ts,
            "base_version": "1.0.0",
            "base_commit": "abc1234",
            "branch": "main",
            "remote": None,
        },
        {},
    )


def _log_metrics(storage, app, verstr, values, ts="2025-01-01T00:00:00Z"):
    storage.append_log_entry(
        app, verstr, "w", {"timestamp": ts, "type": "metrics", "values": values}
    )


def _log_params(storage, app, verstr, values, ts="2025-01-01T00:00:00Z"):
    storage.append_log_entry(
        app, verstr, "w", {"timestamp": ts, "type": "params", "params": values}
    )


def _log_define_metric(storage, app, verstr, name, goal, ts="2025-01-01T00:00:00Z"):
    storage.append_log_entry(
        app,
        verstr,
        "w",
        {"timestamp": ts, "type": "define_metric", "name": name, "goal": goal},
    )


# ---- summary policy ---------------------------------------------------------


def test_diff_uses_summary_not_last(tmp_path):
    """A goal=min metric should show the min, not the last logged value."""
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")

    v1 = "1.0.0-dev.aaa.bbb"
    _save_exp(storage, "myapp", v1)
    _log_define_metric(storage, "myapp", v1, "loss", "min")
    _log_metrics(storage, "myapp", v1, {"loss": 1.0})
    _log_metrics(storage, "myapp", v1, {"loss": 0.002})
    _log_metrics(storage, "myapp", v1, {"loss": 0.005})

    v2 = "1.0.0-dev.ccc.ddd"
    _save_exp(storage, "myapp", v2, ts="2025-01-02T00:00:00Z")
    _log_define_metric(storage, "myapp", v2, "loss", "min", ts="2025-01-02T00:00:00Z")
    _log_metrics(storage, "myapp", v2, {"loss": 0.9})
    _log_metrics(storage, "myapp", v2, {"loss": 0.001})
    _log_metrics(storage, "myapp", v2, {"loss": 0.01})

    result, err = diff_reader.experiment_diff_from_storage(storage, "myapp", v1, v2)

    assert err is None
    delta = result["metrics_delta"]
    # Should show min (0.002) not last (0.005) for v1,
    # and min (0.001) not last (0.01) for v2.
    assert delta["loss"]["from"] == 0.002
    assert delta["loss"]["to"] == 0.001


# ---- goal field --------------------------------------------------------------


def test_diff_delta_carries_goal(tmp_path):
    """Each delta entry must carry its goal from the schema."""
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")

    v1 = "1.0.0-dev.aaa.bbb"
    _save_exp(storage, "myapp", v1)
    _log_define_metric(storage, "myapp", v1, "loss", "min")
    _log_define_metric(storage, "myapp", v1, "acc", "max")
    _log_metrics(storage, "myapp", v1, {"loss": 0.5, "acc": 0.8, "lr": 0.01})

    v2 = "1.0.0-dev.ccc.ddd"
    _save_exp(storage, "myapp", v2, ts="2025-01-02T00:00:00Z")
    _log_define_metric(storage, "myapp", v2, "loss", "min", ts="2025-01-02T00:00:00Z")
    _log_define_metric(storage, "myapp", v2, "acc", "max", ts="2025-01-02T00:00:00Z")
    _log_metrics(storage, "myapp", v2, {"loss": 0.3, "acc": 0.9, "lr": 0.001})

    result, err = diff_reader.experiment_diff_from_storage(storage, "myapp", v1, v2)

    assert err is None
    delta = result["metrics_delta"]
    assert delta["loss"]["goal"] == "min"
    assert delta["acc"]["goal"] == "max"
    # lr has no goal declared
    assert delta["lr"]["goal"] is None


# ---- param field -------------------------------------------------------------


def test_diff_delta_marks_params(tmp_path):
    """A numeric param folded into metrics must be flagged with param=True."""
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")

    v1 = "1.0.0-dev.aaa.bbb"
    _save_exp(storage, "myapp", v1)
    _log_params(storage, "myapp", v1, {"lr": 0.01, "epochs": 10})
    _log_metrics(storage, "myapp", v1, {"loss": 0.5})

    v2 = "1.0.0-dev.ccc.ddd"
    _save_exp(storage, "myapp", v2, ts="2025-01-02T00:00:00Z")
    _log_params(storage, "myapp", v2, {"lr": 0.001, "epochs": 20})
    _log_metrics(storage, "myapp", v2, {"loss": 0.3})

    result, err = diff_reader.experiment_diff_from_storage(storage, "myapp", v1, v2)

    assert err is None
    delta = result["metrics_delta"]
    # lr and epochs are params folded into metrics
    assert delta["lr"]["param"] is True
    assert delta["epochs"]["param"] is True
    # loss is a metric, not a param
    assert delta["loss"]["param"] is False
