"""
Tests for vmn_exp/importers/mlflow_filestore.py

All 12 tests required by the roadmap item B1.

Tests are marked with their roadmap description for traceability.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List

import pytest

# Add tests dir to path so mlflow_fixtures is importable
sys.path.insert(0, str(Path(__file__).parent))

from mlflow_fixtures import MlflowFixtureBuilder
from vmn_exp.importers.mlflow_filestore import iter_runs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RUN_ID_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
RUN_ID_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
RUN_ID_C = "cccccccccccccccccccccccccccccccccccc"
RUN_ID_D = "dddddddddddddddddddddddddddddddddddd"


def _collect(mlruns_path, **kwargs) -> List[dict]:
    return list(iter_runs(mlruns_path, **kwargs))


# ---------------------------------------------------------------------------
# Test 1: skips trash/deleted
# ---------------------------------------------------------------------------


def test_skips_trash_and_deleted(tmp_path):
    """Deleted runs and runs in .trash must not appear in default output."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A, name="active_run")
    b.add_deleted_run("1", RUN_ID_B, name="deleted_run")
    b.add_trashed_run("1", RUN_ID_C, name="trashed_run")

    runs = _collect(tmp_path)
    run_ids = {r["run_id"] for r in runs}
    assert RUN_ID_A in run_ids
    assert RUN_ID_B not in run_ids
    assert RUN_ID_C not in run_ids


def test_include_deleted_includes_deleted_runs(tmp_path):
    """include_deleted=True should surface deleted runs (not trashed ones)."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A, name="active_run")
    b.add_deleted_run("1", RUN_ID_B, name="deleted_run")

    runs = _collect(tmp_path, include_deleted=True)
    run_ids = {r["run_id"] for r in runs}
    assert RUN_ID_A in run_ids
    assert RUN_ID_B in run_ids


# ---------------------------------------------------------------------------
# Test 2: experiment filter
# ---------------------------------------------------------------------------


def test_experiment_filter_by_name(tmp_path):
    """experiments=[name] restricts to that experiment only."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_alpha")
    b.add_experiment("2", "exp_beta")
    b.add_run("1", RUN_ID_A, name="run_in_alpha")
    b.add_run("2", RUN_ID_B, name="run_in_beta")

    runs = _collect(tmp_path, experiments=["exp_alpha"])
    assert len(runs) == 1
    assert runs[0]["run_id"] == RUN_ID_A
    assert runs[0]["experiment_name"] == "exp_alpha"


def test_experiment_filter_by_id(tmp_path):
    """experiments=[id_str] restricts to that experiment only."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_alpha")
    b.add_experiment("2", "exp_beta")
    b.add_run("1", RUN_ID_A)
    b.add_run("2", RUN_ID_B)

    runs = _collect(tmp_path, experiments=["2"])
    assert len(runs) == 1
    assert runs[0]["experiment_id"] == "2"


# ---------------------------------------------------------------------------
# Test 3: nested tag keys via '/' subdirectories
# ---------------------------------------------------------------------------


def test_nested_tag_keys(tmp_path):
    """Tags whose keys contain '/' (stored as subdirs) are read correctly."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run(
        "1",
        RUN_ID_A,
        tags={
            "flat_tag": "flat_value",
            "nested/tag/key": "nested_value",
        },
    )

    runs = _collect(tmp_path)
    assert len(runs) == 1
    tags = runs[0]["tags"]
    assert tags["flat_tag"] == "flat_value"
    assert tags["nested/tag/key"] == "nested_value"


# ---------------------------------------------------------------------------
# Test 4: 2/3-field metric lines
# ---------------------------------------------------------------------------


def test_metric_lines_two_fields(tmp_path):
    """Metric lines with only 2 fields (ts value) are handled; step defaults 0."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A, metrics={"loss": [(1700000001000, 0.5)]})

    runs = _collect(tmp_path)
    rows = list(runs[0]["metrics"]())
    assert len(rows) == 1
    key, val, ts, step = rows[0]
    assert key == "loss"
    assert abs(val - 0.5) < 1e-9
    assert ts == 1700000001000
    assert step == 0


def test_metric_lines_three_fields(tmp_path):
    """Metric lines with 3 fields (ts value step) are parsed correctly."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A, metrics={"acc": [(1700000001000, 0.9, 5)]})

    runs = _collect(tmp_path)
    rows = list(runs[0]["metrics"]())
    assert len(rows) == 1
    key, val, ts, step = rows[0]
    assert key == "acc"
    assert abs(val - 0.9) < 1e-9
    assert step == 5


# ---------------------------------------------------------------------------
# Test 5: malformed files warn (logging) and skip
# ---------------------------------------------------------------------------


def test_malformed_metric_line_warns_and_skips(tmp_path, caplog):
    """A malformed metric line is skipped with a warning; other lines kept."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A)

    # Write a metric file with one good and one bad line
    metric_file = tmp_path / "1" / RUN_ID_A / "metrics" / "loss"
    metric_file.parent.mkdir(parents=True, exist_ok=True)
    metric_file.write_text(
        "1700000001000 0.5 0\nNOT_A_NUMBER bad_value 0\n1700000002000 0.3 1\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        runs = _collect(tmp_path)
        rows = list(runs[0]["metrics"]())

    bad_line_count = sum(1 for r in rows if r is None)
    assert bad_line_count == 0
    # Only 2 valid rows
    assert len(rows) == 2
    # A warning was emitted
    assert any("malform" in rec.message.lower() or "bad" in rec.message.lower() or "skip" in rec.message.lower() or "parse" in rec.message.lower() for rec in caplog.records)


def test_malformed_run_meta_warns_and_skips(tmp_path, caplog):
    """A run with a broken meta.yaml is skipped with a warning."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A, name="good_run")

    # Corrupt the meta.yaml of a second run
    bad_run_dir = tmp_path / "1" / RUN_ID_B
    bad_run_dir.mkdir(parents=True)
    (bad_run_dir / "meta.yaml").write_text(
        ":::not valid yaml:::", encoding="utf-8"
    )

    with caplog.at_level(logging.WARNING):
        runs = _collect(tmp_path)

    run_ids = {r["run_id"] for r in runs}
    assert RUN_ID_A in run_ids
    assert RUN_ID_B not in run_ids
    assert len(caplog.records) >= 1


# ---------------------------------------------------------------------------
# Test 6: int/str status
# ---------------------------------------------------------------------------


def test_status_as_string(tmp_path):
    """Status stored as a string ('FINISHED') is returned as-is."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A, status="FINISHED")

    runs = _collect(tmp_path)
    assert runs[0]["status"] == "FINISHED"


def test_status_as_integer(tmp_path):
    """Status stored as an integer (e.g. 3 = FINISHED) is normalised to str."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    # Write meta.yaml with integer status
    run_dir = tmp_path / "1" / RUN_ID_A
    run_dir.mkdir(parents=True)
    (run_dir / "meta.yaml").write_text(
        "artifact_uri: /tmp/arts\n"
        "end_time: 1700000060000\n"
        "experiment_id: \"1\"\n"
        "lifecycle_stage: active\n"
        "run_id: " + RUN_ID_A + "\n"
        "run_name: test_run\n"
        "run_uuid: " + RUN_ID_A + "\n"
        "start_time: 1700000000000\n"
        "status: 3\n"
        "user_id: test\n",
        encoding="utf-8",
    )

    runs = _collect(tmp_path)
    # 3 == FINISHED in MLflow's RunStatus enum
    assert runs[0]["status"] == "FINISHED"


# ---------------------------------------------------------------------------
# Test 7: missing end_time
# ---------------------------------------------------------------------------


def test_missing_end_time_returns_none(tmp_path):
    """A run with end_time=0 or absent has end_time_ms=None in the neutral dict."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A, end_time=None)

    runs = _collect(tmp_path)
    assert runs[0]["end_time_ms"] is None


def test_positive_end_time_preserved(tmp_path):
    """A run with a real end_time has end_time_ms set."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A, end_time=1700000060000)

    runs = _collect(tmp_path)
    assert runs[0]["end_time_ms"] == 1700000060000


# ---------------------------------------------------------------------------
# Test 8: artifact uri fallback
# ---------------------------------------------------------------------------


def test_artifact_uri_fallback(tmp_path):
    """When artifact_uri is missing from meta.yaml, falls back to <run_dir>/artifacts."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    run_dir = tmp_path / "1" / RUN_ID_A
    run_dir.mkdir(parents=True)
    # Write meta.yaml without artifact_uri
    (run_dir / "meta.yaml").write_text(
        "end_time: 1700000060000\n"
        "experiment_id: \"1\"\n"
        "lifecycle_stage: active\n"
        "run_id: " + RUN_ID_A + "\n"
        "start_time: 1700000000000\n"
        "status: FINISHED\n",
        encoding="utf-8",
    )

    runs = _collect(tmp_path)
    assert len(runs) == 1
    assert runs[0]["artifact_uri"].endswith("artifacts")


# ---------------------------------------------------------------------------
# Test 9: remote uri flagged
# ---------------------------------------------------------------------------


def test_remote_artifact_uri_flagged(tmp_path):
    """A run with an s3:// or gs:// artifact_uri has artifact_remote=True."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A, artifact_uri="s3://my-bucket/mlflow/1/" + RUN_ID_A)

    runs = _collect(tmp_path)
    assert runs[0]["artifact_remote"] is True
    assert runs[0]["artifact_dir"] is None


def test_local_artifact_uri_not_remote(tmp_path):
    """A local file:// or bare path artifact_uri has artifact_remote=False."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A, artifact_uri=str(tmp_path / "arts"))

    runs = _collect(tmp_path)
    assert runs[0]["artifact_remote"] is False
    assert runs[0]["artifact_dir"] == str(tmp_path / "arts")


# ---------------------------------------------------------------------------
# Test 10: datasets
# ---------------------------------------------------------------------------


def test_datasets_parsed(tmp_path):
    """Datasets written in the inputs/dataset_inputs/ layout are parsed."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run(
        "1",
        RUN_ID_A,
        datasets=[
            {
                "name": "train_data",
                "digest": "sha256abc",
                "source_type": "local",
                "source": "/data/train.csv",
            }
        ],
    )

    runs = _collect(tmp_path)
    assert len(runs[0]["datasets"]) == 1
    ds = runs[0]["datasets"][0]
    assert ds["name"] == "train_data"
    assert ds["digest"] == "sha256abc"


def test_datasets_missing_gracefully(tmp_path):
    """A run with no inputs/ directory has an empty datasets list."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A)

    runs = _collect(tmp_path)
    assert runs[0]["datasets"] == []


# ---------------------------------------------------------------------------
# Test 11: metrics lazy
# ---------------------------------------------------------------------------


def test_metrics_callable_lazy(tmp_path):
    """The metrics field is a callable (not pre-loaded); calling it streams rows."""
    b = MlflowFixtureBuilder(tmp_path)
    b.add_experiment("1", "exp_one")
    b.add_run(
        "1",
        RUN_ID_A,
        metrics={
            "loss": [(1700000001000 + i * 1000, 1.0 / (i + 1), i) for i in range(5)],
            "acc": [(1700000001000 + i * 1000, i * 0.1, i) for i in range(5)],
        },
    )

    runs = _collect(tmp_path)
    run = runs[0]

    # metrics must be callable, not a list
    assert callable(run["metrics"])

    rows = list(run["metrics"]())
    assert len(rows) == 10  # 5 loss + 5 acc

    keys = {r[0] for r in rows}
    assert keys == {"loss", "acc"}

    # calling again returns the same data
    rows2 = list(run["metrics"]())
    assert len(rows2) == 10


# ---------------------------------------------------------------------------
# Test 12: real-mlflow roundtrip
# ---------------------------------------------------------------------------


def test_real_mlflow_roundtrip(tmp_path):
    """Log a real run with mlflow then read it back without mlflow."""
    mlflow = pytest.importorskip("mlflow")

    tracking_uri = f"file://{tmp_path / 'mlruns'}"
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("roundtrip_exp")

    with mlflow.start_run(run_name="test_run") as mlflow_run:
        mlflow.log_param("lr", "0.001")
        mlflow.log_metric("loss", 0.5, step=0)
        mlflow.log_metric("loss", 0.3, step=1)
        mlflow.set_tag("my_tag", "hello")
        run_id = mlflow_run.info.run_id

    mlruns_path = tmp_path / "mlruns"
    runs = _collect(mlruns_path)
    assert len(runs) >= 1

    our_runs = [r for r in runs if r["run_id"] == run_id]
    assert len(our_runs) == 1, f"Expected run {run_id} in {[r['run_id'] for r in runs]}"

    run = our_runs[0]
    assert run["name"] == "test_run"
    assert run["params"]["lr"] == "0.001"
    assert run["tags"].get("my_tag") == "hello"

    metric_rows = list(run["metrics"]())
    loss_rows = [(v, s) for k, v, ts, s in metric_rows if k == "loss"]
    assert len(loss_rows) == 2
    assert abs(loss_rows[0][0] - 0.5) < 1e-6
