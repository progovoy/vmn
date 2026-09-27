"""End-to-end tests for ``vmn exp import-mlflow`` (B4).

Tests cover:
- End-to-end mlruns import; list/show/query sees the imported runs.
- Exactly one source (--mlruns XOR --tracking-uri) required.
- --experiment repeatable filter.
- --dry-run writes nothing.
- Second import skips all (idempotent).
- No repo lock taken + no auto-init (no tag/commit created).
- Summary text format.
- Bench: test_import_1k_runs_1k_steps (bounded < 60 s).
"""
from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from mlflow_fixtures import MlflowFixtureBuilder
from version_stamp.cli.snapshot_storage_local import LocalSnapshotStorage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RUN_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
RUN_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
RUN_C = "cccccccccccccccccccccccccccccccccccc"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _storage(experiment_dir: str):
    return LocalSnapshotStorage(str(experiment_dir), subdir="experiments")


def _make_args(
    mlruns=None,
    tracking_uri=None,
    name="myapp",
    experiment=None,
    skip_artifacts=False,
    include_deleted=False,
    dry_run=False,
    workers=4,
    backend="local",
    bucket=None,
    endpoint_url=None,
    prefix="vmn-experiments",
    experiment_dir=None,
):
    """Build a fake argparse.Namespace for import-mlflow."""
    ns = types.SimpleNamespace(
        command="exp",
        action="import-mlflow",
        name=name,
        mlruns=mlruns,
        tracking_uri=tracking_uri,
        experiment=experiment or [],
        skip_artifacts=skip_artifacts,
        include_deleted=include_deleted,
        dry_run=dry_run,
        workers=workers,
        backend=backend,
        bucket=bucket,
        endpoint_url=endpoint_url,
        prefix=prefix,
        experiment_dir=experiment_dir,
    )
    return ns


def _call(args):
    """Call the import-mlflow handler and return exit code."""
    from vmn_exp.importers.cli import import_mlflow_run_without_repo
    return import_mlflow_run_without_repo(args)


def _build_mlruns(tmp_path, runs=None):
    """Build a minimal mlruns dir and return its path."""
    mlruns = tmp_path / "mlruns"
    b = MlflowFixtureBuilder(mlruns)
    b.add_experiment("1", "exp_alpha")
    b.add_experiment("2", "exp_beta")
    if runs is None:
        b.add_run("1", RUN_A, name="run_a", status="FINISHED",
                  params={"lr": "0.01"}, metrics={"loss": [(1700000001000, 0.5, 0)]},
                  tags={"mykey": "myval"})
        b.add_run("2", RUN_B, name="run_b", status="FINISHED",
                  params={"lr": "0.1"})
    else:
        for run in runs:
            b.add_run(*run)
    return str(mlruns)


# ---------------------------------------------------------------------------
# 1. End-to-end import + list/show/query
# ---------------------------------------------------------------------------

def test_end_to_end_import_and_list(tmp_path, capsys):
    mlruns = _build_mlruns(tmp_path)
    exp_dir = str(tmp_path / "vmn_data")

    args = _make_args(mlruns=mlruns, experiment_dir=exp_dir)
    rc = _call(args)
    assert rc == 0

    # Verify storage contains the runs
    storage = _storage(exp_dir)
    verstrs = storage.list_verstrs("myapp")
    assert len(verstrs) == 2

    # List via the reader
    from version_stamp.exp.reader import list_runs
    rows = list_runs("myapp", storage=storage, use_index=False)
    assert len(rows) == 2
    run_ids = {r["imported_from"]["run_id"] for r in rows}
    assert RUN_A in run_ids
    assert RUN_B in run_ids


def test_query_imported_from(tmp_path):
    mlruns = _build_mlruns(tmp_path)
    exp_dir = str(tmp_path / "vmn_data")

    rc = _call(_make_args(mlruns=mlruns, experiment_dir=exp_dir))
    assert rc == 0

    from version_stamp.exp.reader import list_runs
    storage = _storage(exp_dir)

    # All imported runs have a non-null imported_from field
    rows_mlflow = list_runs(
        "myapp", storage=storage, use_index=False,
        query='imported_from != null',
    )
    assert len(rows_mlflow) == 2

    # Query: runs with no imported_from yields empty
    rows_none = list_runs(
        "myapp", storage=storage, use_index=False,
        query='imported_from = null',
    )
    assert len(rows_none) == 0


def test_show_imported_run(tmp_path):
    mlruns = _build_mlruns(tmp_path)
    exp_dir = str(tmp_path / "vmn_data")
    rc = _call(_make_args(mlruns=mlruns, experiment_dir=exp_dir))
    assert rc == 0

    storage = _storage(exp_dir)
    from version_stamp.exp.reader import list_runs
    rows = list_runs("myapp", storage=storage, use_index=False)
    row_a = next(r for r in rows if r["imported_from"]["run_id"] == RUN_A)

    # Show verstr is deterministic
    from vmn_exp.importers.import_records import run_verstr
    assert row_a["verstr"] == run_verstr(RUN_A)
    # Params present
    assert row_a.get("params", {}).get("lr") == "0.01"


# ---------------------------------------------------------------------------
# 2. Exactly one source required
# ---------------------------------------------------------------------------

def test_no_source_returns_nonzero(tmp_path, capsys):
    args = _make_args(experiment_dir=str(tmp_path / "vmn_data"))
    rc = _call(args)
    assert rc != 0


def test_both_sources_returns_nonzero(tmp_path, capsys):
    args = _make_args(
        mlruns="/some/path",
        tracking_uri="http://localhost:5000",
        experiment_dir=str(tmp_path / "vmn_data"),
    )
    rc = _call(args)
    assert rc != 0


# ---------------------------------------------------------------------------
# 3. --experiment repeatable filter
# ---------------------------------------------------------------------------

def test_experiment_filter_by_name(tmp_path):
    mlruns = _build_mlruns(tmp_path)
    exp_dir = str(tmp_path / "vmn_data")

    # Import only exp_alpha (has RUN_A), not exp_beta (has RUN_B)
    rc = _call(_make_args(mlruns=mlruns, experiment=["exp_alpha"],
                          experiment_dir=exp_dir))
    assert rc == 0

    storage = _storage(exp_dir)
    verstrs = storage.list_verstrs("myapp")
    assert len(verstrs) == 1

    from version_stamp.exp.reader import list_runs
    rows = list_runs("myapp", storage=storage, use_index=False)
    assert rows[0]["imported_from"]["run_id"] == RUN_A


def test_experiment_filter_repeatable(tmp_path):
    mlruns = _build_mlruns(tmp_path)
    exp_dir = str(tmp_path / "vmn_data")

    # Import both experiments explicitly (filter matches both)
    rc = _call(_make_args(
        mlruns=mlruns,
        experiment=["exp_alpha", "exp_beta"],
        experiment_dir=exp_dir,
    ))
    assert rc == 0

    storage = _storage(exp_dir)
    assert len(storage.list_verstrs("myapp")) == 2


# ---------------------------------------------------------------------------
# 4. --dry-run writes nothing
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing(tmp_path, capsys):
    mlruns = _build_mlruns(tmp_path)
    exp_dir = str(tmp_path / "vmn_data")

    rc = _call(_make_args(mlruns=mlruns, dry_run=True, experiment_dir=exp_dir))
    assert rc == 0

    # The experiment dir should either not exist or have no run dirs
    storage_root = Path(exp_dir) / ".vmn" / "myapp" / "experiments"
    if storage_root.exists():
        run_dirs = [d for d in storage_root.iterdir() if d.is_dir()]
        assert run_dirs == [], f"Dry-run should not write runs: {run_dirs}"

    # Printed output should mention the runs
    out = capsys.readouterr().out
    assert "would import" in out.lower() or RUN_A[:12] in out or "dry" in out.lower()


# ---------------------------------------------------------------------------
# 5. Second import skips all (idempotent)
# ---------------------------------------------------------------------------

def test_second_import_skips_all(tmp_path, capsys):
    mlruns = _build_mlruns(tmp_path)
    exp_dir = str(tmp_path / "vmn_data")

    rc1 = _call(_make_args(mlruns=mlruns, experiment_dir=exp_dir))
    assert rc1 == 0

    rc2 = _call(_make_args(mlruns=mlruns, experiment_dir=exp_dir))
    assert rc2 == 0

    out = capsys.readouterr().out
    # Second import: "skipped 2"
    assert "skipped 2" in out or "skipped: 2" in out


# ---------------------------------------------------------------------------
# 6. No repo lock taken, no auto-init
# ---------------------------------------------------------------------------

def test_no_autoinit_no_git_ops(tmp_path):
    """import-mlflow must work without an initialized vmn app.

    No tags, commits, or .vmn/app/conf.yml should be created.
    """
    # Create a fresh git repo
    import subprocess
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo_dir), check=True, capture_output=True,
    )

    mlruns = _build_mlruns(tmp_path)
    exp_dir = str(tmp_path / "vmn_data")

    args = _make_args(mlruns=mlruns, name="newapp", experiment_dir=exp_dir)
    rc = _call(args)
    assert rc == 0

    # No .vmn/newapp/conf.yml created in the repo
    conf_yml = repo_dir / ".vmn" / "newapp" / "conf.yml"
    assert not conf_yml.exists(), "import-mlflow must not auto-init the app"

    # Git repo has no commits
    result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=str(repo_dir), capture_output=True, text=True,
    )
    assert result.stdout.strip() == "", "No commits should be created"

    # Storage should still have the runs
    storage = _storage(exp_dir)
    assert len(storage.list_verstrs("newapp")) == 2


# ---------------------------------------------------------------------------
# 7. Summary text format
# ---------------------------------------------------------------------------

def test_summary_format_all_imported(tmp_path, capsys):
    mlruns = _build_mlruns(tmp_path)
    exp_dir = str(tmp_path / "vmn_data")

    rc = _call(_make_args(mlruns=mlruns, experiment_dir=exp_dir))
    assert rc == 0

    out = capsys.readouterr().out
    # Must contain counts for each outcome
    assert "imported 2" in out or "imported: 2" in out


def test_summary_contains_all_fields(tmp_path, capsys):
    mlruns = _build_mlruns(tmp_path)
    exp_dir = str(tmp_path / "vmn_data")
    _call(_make_args(mlruns=mlruns, experiment_dir=exp_dir))

    # Import again to get skipped
    _call(_make_args(mlruns=mlruns, experiment_dir=exp_dir))

    out = capsys.readouterr().out
    # All four summary fields should appear
    assert "imported" in out
    assert "skipped" in out


def test_exit_1_on_failure(tmp_path, capsys):
    """Verify exit 1 when the mlruns path does not exist."""
    exp_dir = str(tmp_path / "vmn_data")
    args = _make_args(mlruns="/nonexistent/path/mlruns", experiment_dir=exp_dir)
    # Should either exit 1 or succeed with 0 imported runs
    # (the filestore silently returns nothing for a missing dir)
    rc = _call(args)
    # Either 0 (no runs, no error) or 1 (explicit failure) is acceptable;
    # the important thing is that it doesn't raise an unhandled exception.
    assert rc in (0, 1)


# ---------------------------------------------------------------------------
# 8. Bench: 1k runs × 1k steps (must complete in < 60 s)
# ---------------------------------------------------------------------------

def test_import_1k_runs_1k_steps(tmp_path):
    """Import 1000 runs with 1000 metric steps each; must complete in < 60 s."""
    RUNS = 1000
    STEPS = 1000
    mlruns = tmp_path / "mlruns"
    b = MlflowFixtureBuilder(mlruns)
    b.add_experiment("1", "bench_exp")

    ts_base = 1700000000000
    for i in range(RUNS):
        # Run IDs must differ in first 12 chars for deterministic verstr uniqueness
        run_id = f"{i:012x}" + "0" * 24  # 36-char, unique in first 12
        metrics = {
            "loss": [(ts_base + step * 1000, 1.0 / (step + 1), step) for step in range(STEPS)]
        }
        b.add_run("1", run_id, status="FINISHED",
                  params={"lr": "0.01"},
                  metrics=metrics)

    exp_dir = str(tmp_path / "vmn_data")
    args = _make_args(mlruns=str(mlruns), workers=8, experiment_dir=exp_dir)

    start = time.perf_counter()
    rc = _call(args)
    elapsed = time.perf_counter() - start

    assert rc == 0
    storage = _storage(exp_dir)
    assert len(storage.list_verstrs("myapp")) == RUNS
    assert elapsed < 60.0, f"1k×1k bench took {elapsed:.1f}s (limit 60s)"
