#!/usr/bin/env python3
"""Tests for UI experiment reader functions with storage backends (S3/local)."""
import json
import os

import boto3
import pytest
import yaml
from moto import mock_aws

from version_stamp.cli.snapshot import LocalSnapshotStorage, S3SnapshotStorage
from version_stamp.core.logging import init_stamp_logger
from version_stamp.ui.readers import diffs as diff_reader
from version_stamp.ui.readers import experiments as exp_reader


@pytest.fixture(autouse=True)
def _init_logger():
    try:
        init_stamp_logger()
    except Exception:
        pass


def _save_exp_with_log(storage, app, verstr, metrics=None, ts="2025-01-01T00:00:00Z"):
    """Save experiment metadata + a log with optional metrics."""
    storage.save(app, verstr, {
        "verstr": verstr, "app_name": app, "timestamp": ts,
        "base_version": "1.0.0", "base_commit": "abc1234",
        "branch": "main", "remote": None,
    }, {})
    if metrics:
        storage.append_log_entry(app, verstr, "test-writer",
            {"timestamp": ts, "type": "metrics", "values": metrics})


# -- J. UI reader functions --------------------------------------------------


def test_list_experiments_from_storage(tmp_path):
    """list_experiments_from_storage returns rows with correct metrics."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")

    _save_exp_with_log(storage, "myapp", "1.0.0-dev.aaa.bbb",
                       metrics={"loss": 0.5, "acc": 0.9},
                       ts="2025-01-01T00:00:00Z")
    _save_exp_with_log(storage, "myapp", "1.0.0-dev.ccc.ddd",
                       metrics={"loss": 0.3, "acc": 0.95},
                       ts="2025-01-02T00:00:00Z")

    rows = exp_reader.list_experiments_from_storage(storage, "myapp")

    assert len(rows) == 2
    assert rows[0]["verstr"] == "1.0.0-dev.aaa.bbb"
    assert rows[0]["metrics"]["loss"] == 0.5
    assert rows[1]["verstr"] == "1.0.0-dev.ccc.ddd"
    assert rows[1]["metrics"]["acc"] == 0.95


def test_get_experiment_from_storage(tmp_path):
    """get_experiment_from_storage returns full detail dict."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")

    _save_exp_with_log(storage, "myapp", "1.0.0-dev.aaa.bbb",
                       metrics={"loss": 0.42}, ts="2025-01-01T00:00:00Z")

    result, err = exp_reader.get_experiment_from_storage(
        storage, "myapp", "1.0.0-dev.aaa.bbb")

    assert err is None
    assert result is not None
    assert result["metadata"]["verstr"] == "1.0.0-dev.aaa.bbb"
    assert result["metrics"]["loss"] == 0.42
    assert isinstance(result["log"], list)
    assert len(result["log"]) > 0
    assert "series" in result
    assert "artifacts_dir" in result
    assert "patches" in result
    for key in ("working_tree", "local_commits", "untracked_files"):
        assert key in result["patches"]
        assert result["patches"][key] is False


def test_get_experiment_from_storage_not_found(tmp_path):
    """get_experiment_from_storage returns error for missing experiment."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")

    result, err = exp_reader.get_experiment_from_storage(
        storage, "myapp", "1.0.0-dev.nonexistent.xxx")

    assert result is None
    assert "not found" in err.lower() or "not found" in err


@mock_aws
def test_list_apps_from_storage():
    """list_apps_from_storage discovers apps from S3 prefixes."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    storage = S3SnapshotStorage("test-bucket", prefix="vmn-experiments")

    _save_exp_with_log(storage, "app_a", "1.0.0-dev.aaa.bbb",
                       ts="2025-01-01T00:00:00Z")
    _save_exp_with_log(storage, "app_b", "2.0.0-dev.ccc.ddd",
                       ts="2025-01-02T00:00:00Z")

    rows = exp_reader.list_apps_from_storage(storage)

    names = [r["name"] for r in rows]
    assert "app/a" in names or "app_a" in names
    assert "app/b" in names or "app_b" in names
    assert len(rows) == 2
    for row in rows:
        assert "experiments" in row
        assert row["experiments"] >= 1
        assert row["versions"] == 0


def test_fetch_experiment_rows_with_storage(tmp_path):
    """fetch_experiment_rows accepts a storage= parameter directly."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")

    _save_exp_with_log(storage, "myapp", "1.0.0-dev.aaa.bbb",
                       metrics={"lr": 0.001}, ts="2025-01-01T00:00:00Z")

    rows = exp_reader.fetch_experiment_rows(app_name="myapp", storage=storage)

    assert len(rows) == 1
    row = rows[0]
    assert row["verstr"] == "1.0.0-dev.aaa.bbb"
    assert row["idx"] == 1
    assert row["metrics"]["lr"] == 0.001
    assert "timestamp" in row
    assert "branch" in row
    assert "base_version" in row


def test_fetch_experiment_rows_with_jsonl_logs(tmp_path):
    """Rows include merged metrics from per-writer JSONL log files."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")

    _save_exp_with_log(storage, "myapp", "1.0.0-dev.aaa.bbb",
                       ts="2025-01-01T00:00:00Z")

    # Append from two different writers
    storage.append_log_entry("myapp", "1.0.0-dev.aaa.bbb", "worker-0",
        {"timestamp": "2025-01-01T00:01:00Z", "type": "metrics",
         "values": {"loss": 0.8}})
    storage.append_log_entry("myapp", "1.0.0-dev.aaa.bbb", "worker-1",
        {"timestamp": "2025-01-01T00:02:00Z", "type": "metrics",
         "values": {"loss": 0.5, "acc": 0.9}})

    rows = exp_reader.fetch_experiment_rows(app_name="myapp", storage=storage)

    assert len(rows) == 1
    # Latest values win: worker-1 wrote loss=0.5 and acc=0.9 after worker-0
    assert rows[0]["metrics"]["loss"] == 0.5
    assert rows[0]["metrics"]["acc"] == 0.9


# -- K. UI diff reader -------------------------------------------------------


def test_experiment_diff_from_storage(tmp_path):
    """experiment_diff_from_storage returns metrics_delta and diff: None."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")

    _save_exp_with_log(storage, "myapp", "1.0.0-dev.aaa.bbb",
                       metrics={"loss": 0.8, "acc": 0.7},
                       ts="2025-01-01T00:00:00Z")
    _save_exp_with_log(storage, "myapp", "1.0.0-dev.ccc.ddd",
                       metrics={"loss": 0.3, "acc": 0.95},
                       ts="2025-01-02T00:00:00Z")

    result, err = diff_reader.experiment_diff_from_storage(
        storage, "myapp", "1.0.0-dev.aaa.bbb", "1.0.0-dev.ccc.ddd")

    assert err is None
    assert result is not None
    assert result["diff"] is None  # Tree diffs unavailable for storage backends
    assert result["from_verstr"] == "1.0.0-dev.aaa.bbb"
    assert result["to_verstr"] == "1.0.0-dev.ccc.ddd"

    delta = result["metrics_delta"]
    assert "loss" in delta
    assert delta["loss"]["from"] == 0.8
    assert delta["loss"]["to"] == 0.3
    assert "acc" in delta
    assert delta["acc"]["from"] == 0.7
    assert delta["acc"]["to"] == 0.95


def test_experiment_diff_from_storage_not_found(tmp_path):
    """experiment_diff_from_storage returns error when one ref is missing."""
    storage = LocalSnapshotStorage(str(tmp_path), subdir="experiments")

    _save_exp_with_log(storage, "myapp", "1.0.0-dev.aaa.bbb",
                       ts="2025-01-01T00:00:00Z")

    result, err = diff_reader.experiment_diff_from_storage(
        storage, "myapp", "1.0.0-dev.aaa.bbb", "1.0.0-dev.nonexistent.xxx")

    assert result is None
    assert err is not None
    assert "not found" in err.lower() or "not found" in err
