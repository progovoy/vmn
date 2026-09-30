"""Tests for vmn_exp/importers/import_records.py (B3).

17 tests covering: verstr determinism, re-import noop, partial import resume,
index ordering, params, metrics grouping, NaN kept, status mapping (x3),
tags mapping, parent linkage, datasets→inputs, artifacts copied,
remote artifacts not copied, one batch writer id, list_runs/query imported_from.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from mlflow_fixtures import MlflowFixtureBuilder
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.importers.import_records import import_run, run_verstr

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

RUN_ID_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # 36 chars
RUN_ID_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
RUN_ID_PARENT = "pppppppppppppppppppppppppppppppppppp"


def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), subdir="experiments")


def _simple_run(mlruns_path, run_id, *, start_time=1700000000000, **kwargs):
    """Build a MlflowFixtureBuilder with a single run and return the run dict."""
    from vmn_exp.importers.mlflow_filestore import iter_runs
    b = MlflowFixtureBuilder(mlruns_path)
    b.add_experiment("1", "exp_one")
    b.add_run("1", run_id, start_time=start_time, **kwargs)
    return next(iter_runs(mlruns_path))


# ---------------------------------------------------------------------------
# 1. verstr is deterministic
# ---------------------------------------------------------------------------


def test_verstr_deterministic():
    verstr = run_verstr(RUN_ID_A)
    expected = "0.0.0-mlflow." + RUN_ID_A[:12]
    assert verstr == expected


def test_verstr_deterministic_same_id():
    assert run_verstr(RUN_ID_A) == run_verstr(RUN_ID_A)


# ---------------------------------------------------------------------------
# 2. re-import noop → "skipped"
# ---------------------------------------------------------------------------


def test_reimport_noop(tmp_path):
    mlruns = tmp_path / "mlruns"
    run = _simple_run(mlruns, RUN_ID_A, status="FINISHED")
    storage = _storage(tmp_path)

    r1 = import_run(storage, "myapp", run)
    r2 = import_run(storage, "myapp", run)

    assert r1 == "created"
    assert r2 == "skipped"


# ---------------------------------------------------------------------------
# 3. partial import → "resumed"
#    Simulate: dir claimed + metadata written but no log entries.
# ---------------------------------------------------------------------------


def test_partial_import_resume(tmp_path):
    mlruns = tmp_path / "mlruns"
    run = _simple_run(mlruns, RUN_ID_A, status="FINISHED")
    storage = _storage(tmp_path)

    # Simulate a partial import: manually write the metadata without a log
    from vmn_exp.core.writer import claim_record
    verstr = run_verstr(RUN_ID_A)
    metadata = {
        "verstr": verstr,
        "code_verstr": verstr,
        "imported_from": {
            "tool": "mlflow",
            "run_id": RUN_ID_A,
            "experiment_id": "1",
            "experiment_name": "exp_one",
            "source_commit": None,
            "artifact_uri": run["artifact_uri"],
        },
    }
    claimed = claim_record(storage, "myapp", verstr, metadata)
    assert claimed  # first claim succeeds

    # Now try to import — should detect partial and resume
    result = import_run(storage, "myapp", run)
    assert result == "resumed"

    # After resume, the log should exist
    logs = storage.load_logs_by_writer("myapp", verstr)
    flat = [e for entries in logs.values() for e in entries]
    assert any(e.get("type") == "create" for e in flat)


# ---------------------------------------------------------------------------
# 4. index orders by start_time
# ---------------------------------------------------------------------------


def test_index_orders_by_start_time(tmp_path):
    from vmn_exp.importers.mlflow_filestore import iter_runs
    mlruns = tmp_path / "mlruns"
    b = MlflowFixtureBuilder(mlruns)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_B, name="second", start_time=1700001000000, status="FINISHED")
    b.add_run("1", RUN_ID_A, name="first", start_time=1700000000000, status="FINISHED")

    storage = _storage(tmp_path)
    for r in iter_runs(mlruns):
        import_run(storage, "myapp", r)

    from vmn_exp.sdk.reader import list_runs
    rows = list_runs("myapp", storage=storage, use_index=False)
    # ordered by start_time ascending
    assert rows[0]["verstr"] == run_verstr(RUN_ID_A)
    assert rows[1]["verstr"] == run_verstr(RUN_ID_B)


# ---------------------------------------------------------------------------
# 5. params go into create log entry
# ---------------------------------------------------------------------------


def test_params_in_create_entry(tmp_path):
    mlruns = tmp_path / "mlruns"
    run = _simple_run(mlruns, RUN_ID_A, params={"lr": "0.01", "epochs": "10"})
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)

    verstr = run_verstr(RUN_ID_A)
    logs = storage.load_merged_log("myapp", verstr)
    create_entry = next(e for e in logs if e.get("type") == "create")
    assert create_entry.get("params") == {"lr": "0.01", "epochs": "10"}


# ---------------------------------------------------------------------------
# 6. metrics grouped by (timestamp, step)
# ---------------------------------------------------------------------------


def test_metrics_grouped_by_ts_step(tmp_path):
    mlruns = tmp_path / "mlruns"
    b = MlflowFixtureBuilder(mlruns)
    b.add_experiment("1", "exp_one")
    b.add_run(
        "1", RUN_ID_A,
        metrics={
            "loss": [(1700000001000, 0.5, 0), (1700000002000, 0.3, 1)],
            "acc": [(1700000001000, 0.9, 0), (1700000002000, 0.95, 1)],
        },
    )
    from vmn_exp.importers.mlflow_filestore import iter_runs
    run = next(iter_runs(mlruns))
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)

    verstr = run_verstr(RUN_ID_A)
    logs = storage.load_merged_log("myapp", verstr)
    metric_entries = [e for e in logs if e.get("type") == "metrics"]
    # ts=1700000001000, step=0 → one entry with both loss and acc
    # ts=1700000002000, step=1 → another entry with both
    assert len(metric_entries) == 2
    steps = {e.get("step") for e in metric_entries}
    assert steps == {0, 1}
    # Each entry has values for both keys at that step
    step0 = next(e for e in metric_entries if e.get("step") == 0)
    assert "loss" in step0.get("values", {})
    assert "acc" in step0.get("values", {})


# ---------------------------------------------------------------------------
# 7. NaN values kept in log
# ---------------------------------------------------------------------------


def test_nan_kept_in_metrics(tmp_path):
    mlruns = tmp_path / "mlruns"
    b = MlflowFixtureBuilder(mlruns)
    b.add_experiment("1", "exp_one")
    b.add_run(
        "1", RUN_ID_A,
        metrics={"loss": [(1700000001000, float("nan"), 0)]},
    )
    from vmn_exp.importers.mlflow_filestore import iter_runs
    run = next(iter_runs(mlruns))
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)

    verstr = run_verstr(RUN_ID_A)
    logs = storage.load_merged_log("myapp", verstr)
    metric_entries = [e for e in logs if e.get("type") == "metrics"]
    assert len(metric_entries) == 1
    assert math.isnan(metric_entries[0]["values"]["loss"])


# ---------------------------------------------------------------------------
# 8-10. Status mapping: FINISHED→succeeded, FAILED/KILLED→failed, RUNNING→stuck
# ---------------------------------------------------------------------------


def _get_run_state(storage, app_name, verstr):
    import yaml
    from vmn_exp.core.status import RUN_STATE_FILE
    snap_dir = storage._snapshot_dir(app_name, verstr)
    path = os.path.join(snap_dir, RUN_STATE_FILE)
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def test_status_finished_maps_to_succeeded(tmp_path):
    mlruns = tmp_path / "mlruns"
    run = _simple_run(mlruns, RUN_ID_A, status="FINISHED")
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)
    state = _get_run_state(storage, "myapp", run_verstr(RUN_ID_A))
    assert state.get("exit_code") == 0


def test_status_failed_maps_to_failed(tmp_path):
    mlruns = tmp_path / "mlruns"
    run = _simple_run(mlruns, RUN_ID_A, status="FAILED")
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)
    state = _get_run_state(storage, "myapp", run_verstr(RUN_ID_A))
    assert state.get("exit_code") == 1


def test_status_running_maps_to_stuck(tmp_path):
    """RUNNING status → no exit code + very old heartbeat so status derives as stuck."""
    mlruns = tmp_path / "mlruns"
    run = _simple_run(mlruns, RUN_ID_A, status="RUNNING")
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)
    state = _get_run_state(storage, "myapp", run_verstr(RUN_ID_A))
    assert "exit_code" not in state
    # Heartbeat must be far in the past (epoch 0 or very old ISO)
    hb = state.get("heartbeat")
    assert hb is not None


# ---------------------------------------------------------------------------
# 11. tags mapping: mlflow.* internals skipped (except already-mapped fields)
# ---------------------------------------------------------------------------


def test_tags_mapping_skips_mlflow_internals(tmp_path):
    mlruns = tmp_path / "mlruns"
    b = MlflowFixtureBuilder(mlruns)
    b.add_experiment("1", "exp_one")
    b.add_run(
        "1", RUN_ID_A,
        tags={
            "mlflow.runName": "my_run",
            "mlflow.source.name": "train.py",
            "mlflow.source.type": "LOCAL",
            "my_tag": "hello",
        },
    )
    from vmn_exp.importers.mlflow_filestore import iter_runs
    run = next(iter_runs(mlruns))
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)

    verstr = run_verstr(RUN_ID_A)
    logs = storage.load_merged_log("myapp", verstr)
    tag_entries = [e for e in logs if e.get("type") == "tags"]
    all_tags = {}
    for e in tag_entries:
        all_tags.update(e.get("set", {}))

    # my_tag must appear
    assert "my_tag" in all_tags
    # mlflow.source.* internals must NOT appear
    assert "mlflow.source.name" not in all_tags
    assert "mlflow.source.type" not in all_tags


# ---------------------------------------------------------------------------
# 12. parent linkage
# ---------------------------------------------------------------------------


def test_parent_linkage(tmp_path):
    from vmn_exp.importers.mlflow_filestore import iter_runs
    mlruns = tmp_path / "mlruns"
    b = MlflowFixtureBuilder(mlruns)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_PARENT, name="parent_run")
    b.add_run("1", RUN_ID_A, name="child_run",
              tags={"mlflow.parentRunId": RUN_ID_PARENT})

    storage = _storage(tmp_path)
    for r in iter_runs(mlruns):
        import_run(storage, "myapp", r)

    verstr_child = run_verstr(RUN_ID_A)
    # Load metadata for child
    meta = storage.load_metadata("myapp", verstr_child)
    assert meta.get("parent") == run_verstr(RUN_ID_PARENT)


# ---------------------------------------------------------------------------
# 13. datasets → input entries
# ---------------------------------------------------------------------------


def test_datasets_become_input_entries(tmp_path):
    mlruns = tmp_path / "mlruns"
    b = MlflowFixtureBuilder(mlruns)
    b.add_experiment("1", "exp_one")
    b.add_run(
        "1", RUN_ID_A,
        datasets=[{"name": "train_ds", "digest": "sha:abc", "source": "s3://bucket/data"}],
    )
    from vmn_exp.importers.mlflow_filestore import iter_runs
    run = next(iter_runs(mlruns))
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)

    verstr = run_verstr(RUN_ID_A)
    logs = storage.load_merged_log("myapp", verstr)
    input_entries = [e for e in logs if e.get("type") == "input"]
    assert len(input_entries) == 1
    assert input_entries[0]["name"] == "train_ds"


# ---------------------------------------------------------------------------
# 14. local artifacts are copied
# ---------------------------------------------------------------------------


def test_local_artifacts_copied(tmp_path):
    mlruns = tmp_path / "mlruns"
    b = MlflowFixtureBuilder(mlruns)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A)
    # Create a real artifact file in the artifact dir
    artifact_dir = mlruns / "1" / RUN_ID_A / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "model.txt").write_text("hello model", encoding="utf-8")

    from vmn_exp.importers.mlflow_filestore import iter_runs
    run = next(iter_runs(mlruns))
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)

    # The artifact should appear in storage
    verstr = run_verstr(RUN_ID_A)
    artifacts = storage.list_artifacts("myapp", verstr)
    assert any("model.txt" in a["name"] for a in artifacts)


# ---------------------------------------------------------------------------
# 15. remote artifacts not copied
# ---------------------------------------------------------------------------


def test_remote_artifacts_not_copied(tmp_path):
    mlruns = tmp_path / "mlruns"
    b = MlflowFixtureBuilder(mlruns)
    b.add_experiment("1", "exp_one")
    b.add_run("1", RUN_ID_A, artifact_uri="s3://mybucket/mlflow/artifacts")

    from vmn_exp.importers.mlflow_filestore import iter_runs
    run = next(iter_runs(mlruns))
    assert run["artifact_remote"]
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)

    verstr = run_verstr(RUN_ID_A)
    artifacts = storage.list_artifacts("myapp", verstr)
    assert len(artifacts) == 0


# ---------------------------------------------------------------------------
# 16. all log lines written as one batch with writer id "mlflow-import"
# ---------------------------------------------------------------------------


def test_one_batch_writer_id(tmp_path):
    mlruns = tmp_path / "mlruns"
    b = MlflowFixtureBuilder(mlruns)
    b.add_experiment("1", "exp_one")
    b.add_run(
        "1", RUN_ID_A,
        params={"k": "v"},
        metrics={"loss": [(1700000001000, 0.5, 0)]},
        tags={"my_tag": "x"},
    )
    from vmn_exp.importers.mlflow_filestore import iter_runs
    run = next(iter_runs(mlruns))
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)

    verstr = run_verstr(RUN_ID_A)
    logs_by_writer = storage.load_logs_by_writer("myapp", verstr)
    # Only the "mlflow-import" writer should have entries
    writers_with_entries = [w for w, e in logs_by_writer.items() if e]
    assert writers_with_entries == ["mlflow-import"]


# ---------------------------------------------------------------------------
# 17. list_runs / query shows imported_from
# ---------------------------------------------------------------------------


def test_list_runs_shows_imported_from(tmp_path):
    mlruns = tmp_path / "mlruns"
    run = _simple_run(mlruns, RUN_ID_A, status="FINISHED")
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)

    from vmn_exp.sdk.reader import list_runs
    rows = list_runs("myapp", storage=storage, use_index=False)
    assert len(rows) == 1
    row = rows[0]
    assert row.get("imported_from", {}).get("run_id") == RUN_ID_A
    assert row["imported_from"]["tool"] == "mlflow"


def test_list_runs_query_imported_from(tmp_path):
    mlruns = tmp_path / "mlruns"
    run = _simple_run(mlruns, RUN_ID_A, status="FINISHED")
    storage = _storage(tmp_path)
    import_run(storage, "myapp", run)

    from vmn_exp.sdk.reader import list_runs
    rows_match = list_runs(
        "myapp", storage=storage, use_index=False,
        query="imported_from = null"
    )
    rows_nomatch = list_runs(
        "myapp", storage=storage, use_index=False,
        query='imported_from != null'
    )
    assert len(rows_match) == 0
    assert len(rows_nomatch) == 1
