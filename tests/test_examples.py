"""Every script in examples/ is executed here, not merely imported.

Examples rot silently: they keep importing fine long after the behaviour they
demonstrate changed. So each one runs as a real subprocess against a real repo
(the ``app_layout`` fixture's git checkout with its bare remote), and the test
asserts what it actually recorded rather than that it exited quietly.
"""
import os
import subprocess

import pytest
from helpers import _PROJECT_ROOT, _PY, _storage

from version_stamp.exp.reader import get_run, list_runs

EXAMPLES_DIR = os.path.join(_PROJECT_ROOT, "examples")

# The app every example writes to; deliberately not a name a real project uses.
APP_NAME = "vmn_examples"

COVERED = (
    "01_minimal.py",
    "02_training_loop.py",
    "03_sweep.py",
    "04_query.py",
    "05_autolog_sklearn.py",
)


def _run_example(app_layout, name):
    env = dict(os.environ)
    env["VMN_WORKING_DIR"] = app_layout.repo_path
    # Import the version_stamp under test, not the venv's editable install of
    # the main checkout.
    env["PYTHONPATH"] = _PROJECT_ROOT
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        env.pop(key, None)

    proc = subprocess.run(
        [_PY, os.path.join(EXAMPLES_DIR, name)],
        cwd=app_layout.repo_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"{name} failed:\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout


def _runs(app_layout, **kwargs):
    return list_runs(APP_NAME, storage=_storage(app_layout), **kwargs)


def test_every_example_is_covered_by_a_test():
    scripts = sorted(f for f in os.listdir(EXAMPLES_DIR) if f.endswith(".py"))
    assert scripts == sorted(COVERED)
    assert os.path.isfile(os.path.join(EXAMPLES_DIR, "README.md"))


def test_01_minimal_records_one_run_with_its_metrics(app_layout):
    out = _run_example(app_layout, "01_minimal.py")

    rows = _runs(app_layout)
    assert len(rows) == 1
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["metrics"]["loss"] == pytest.approx(0.2)
    assert rows[0]["verstr"] in out


def test_02_training_loop_records_params_note_artifact_and_sys_metrics(app_layout):
    out = _run_example(app_layout, "02_training_loop.py")

    rows = _runs(app_layout)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "succeeded"
    assert row["params"]["optimizer"] == "adam"
    assert row["params"]["lr"] == 0.001
    assert "loss" in row["metrics"] and "accuracy" in row["metrics"]
    # system_metrics=True samples on every heartbeat, so a run longer than one
    # beat must have recorded its own resource usage.
    assert "sys_rss_mb" in row["metrics"], row["metrics"]

    full = get_run(APP_NAME, ref=row["verstr"], storage=_storage(app_layout))
    assert [a["name"] for a in full["artifacts"]] == ["metrics.json"]
    # Per-step metrics are a curve, not one number.
    assert len(full["series"]["loss"]) > 1
    assert row["verstr"] in out


def test_03_sweep_builds_one_outer_run_over_three_inner_runs(app_layout):
    out = _run_example(app_layout, "03_sweep.py")

    rows = _runs(app_layout)
    outer = [r for r in rows if r["kind"] == "outer"]
    inner = [r for r in rows if r["kind"] == "inner"]
    assert len(outer) == 1
    assert len(inner) == 3
    assert all(r["parent"] == outer[0]["verstr"] for r in inner)
    assert outer[0]["tree_status"] == "succeeded"
    assert sorted(r["params"]["lr"] for r in inner) == [0.0001, 0.0003, 0.001]
    assert outer[0]["verstr"] in out


def test_04_query_prints_the_rows_each_query_matches(app_layout):
    out = _run_example(app_layout, "04_query.py")

    rows = _runs(app_layout)
    assert len(rows) == 4
    assert sorted(r["status"] for r in rows) == [
        "failed",
        "succeeded",
        "succeeded",
        "succeeded",
    ]

    matched = [line for line in out.splitlines() if line.startswith("matched ")]
    assert matched == [
        "matched 4 runs",
        "matched 1 run",
        "matched 2 runs",
        "matched 1 run",
    ], out
    assert 'params.example = "04_query"' in out


def test_05_autolog_sklearn_records_the_fit_without_logging_calls(app_layout):
    pytest.importorskip("sklearn")

    out = _run_example(app_layout, "05_autolog_sklearn.py")

    rows = _runs(app_layout)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "succeeded"
    assert row["params"]["sklearn_estimator"] == "LogisticRegression"
    assert "sklearn_score" in row["metrics"]
    assert "sklearn_estimator" in out

    full = get_run(APP_NAME, ref=row["verstr"], storage=_storage(app_layout))
    assert [a["name"] for a in full["artifacts"]] == ["sklearn_LogisticRegression.pkl"]
