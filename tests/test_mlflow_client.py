"""Tests for vmn_exp/importers/mlflow_client.py using a fake MlflowClient.

No real mlflow installation is needed — all MLflow objects are fakes.
"""
import importlib
import sys
import types
from dataclasses import dataclass, field
from typing import List, Optional
import pytest


# ---------------------------------------------------------------------------
# Fake MLflow object tree
# ---------------------------------------------------------------------------

@dataclass
class FakeMetric:
    key: str
    value: float
    timestamp: int
    step: int


@dataclass
class FakeRunInfo:
    run_id: str
    experiment_id: str
    run_name: str
    start_time: int
    end_time: Optional[int]
    artifact_uri: str
    status: str          # 'FINISHED', 'FAILED', 'KILLED', 'RUNNING', 'SCHEDULED'
    lifecycle_stage: str = "active"


@dataclass
class FakeRunData:
    params: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)  # latest values only


@dataclass
class FakeRun:
    info: FakeRunInfo
    data: FakeRunData


@dataclass
class FakeExperiment:
    experiment_id: str
    name: str
    lifecycle_stage: str = "active"  # 'active' | 'deleted'


class FakePage(list):
    """A list that also carries an MLflow page token."""

    def __init__(self, items, token=None):
        super().__init__(items)
        self.token = token


class FakeMlflowClient:
    """Minimal fake MlflowClient."""

    def __init__(self, experiments: List[FakeExperiment], runs_by_exp: dict,
                 metrics_by_run: dict = None, artifact_files: dict = None):
        """
        experiments: list of FakeExperiment
        runs_by_exp: {exp_id: [FakeRun, ...]}
        metrics_by_run: {run_id: {key: [FakeMetric, ...]}}
        artifact_files: {run_id: [str, ...]}  — file paths under artifact root
        """
        self._experiments = experiments
        self._runs_by_exp = runs_by_exp
        self._metrics = metrics_by_run or {}
        self._artifact_files = artifact_files or {}
        self.search_experiments_calls = []
        self.search_runs_calls = []
        self.get_metric_history_calls = []
        self.download_artifacts_calls = []

    def search_experiments(self, view_type=None, page_token=None, max_results=1000):
        self.search_experiments_calls.append((view_type, page_token))
        exps = self._experiments
        if view_type == "ACTIVE_ONLY":
            exps = [e for e in exps if getattr(e, "lifecycle_stage", "active") == "active"]
        # Simple pagination: page_token is a string offset into the filtered list
        offset = int(page_token) if page_token else 0
        page = exps[offset:offset + 2]
        next_token = str(offset + 2) if offset + 2 < len(exps) else None
        return FakePage(page, token=next_token)

    def search_runs(self, experiment_ids, page_token=None, run_view_type=None,
                    max_results=1000):
        self.search_runs_calls.append((tuple(experiment_ids), page_token))
        all_runs = []
        for exp_id in experiment_ids:
            all_runs.extend(self._runs_by_exp.get(exp_id, []))
        if run_view_type == "ACTIVE_ONLY":
            all_runs = [r for r in all_runs
                        if getattr(r.info, "lifecycle_stage", "active") == "active"]
        offset = int(page_token) if page_token else 0
        page = all_runs[offset:offset + 2]
        next_token = str(offset + 2) if offset + 2 < len(all_runs) else None
        return FakePage(page, token=next_token)

    def get_metric_history(self, run_id, key):
        self.get_metric_history_calls.append((run_id, key))
        return self._metrics.get(run_id, {}).get(key, [])

    def download_artifacts(self, run_id, path, dst_path):
        self.download_artifacts_calls.append((run_id, path, dst_path))
        import os
        os.makedirs(dst_path, exist_ok=True)
        dest = os.path.join(dst_path, "artifact.txt")
        with open(dest, "w") as f:
            f.write(f"artifact for {run_id}/{path}")
        return dest


# ---------------------------------------------------------------------------
# Helpers to (re)import the module under test cleanly
# ---------------------------------------------------------------------------

MODULE = "vmn_exp.importers.mlflow_client"


def fresh_import():
    """Import (or reimport) the module under test."""
    for key in list(sys.modules):
        if key == MODULE or key.startswith(MODULE + "."):
            del sys.modules[key]
    return importlib.import_module(MODULE)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_paginates_experiments_and_runs():
    """iter_runs fetches all pages of experiments and all pages of runs."""
    exps = [FakeExperiment(str(i), f"exp{i}") for i in range(5)]
    runs_by_exp = {
        "0": [FakeRun(FakeRunInfo("r0", "0", "run0", 1000, 2000,
                                  "mlflow-artifacts:/0/r0", "FINISHED"), FakeRunData())],
        "1": [
            FakeRun(FakeRunInfo("r1a", "1", "run1a", 1001, None,
                                "mlflow-artifacts:/1/r1a", "RUNNING"), FakeRunData()),
            FakeRun(FakeRunInfo("r1b", "1", "run1b", 1002, 1500,
                                "mlflow-artifacts:/1/r1b", "FAILED"), FakeRunData()),
        ],
    }
    client = FakeMlflowClient(exps, runs_by_exp)
    mod = fresh_import()
    results = list(mod.iter_runs("fake://uri", client=client))
    run_ids = {r["run_id"] for r in results}
    assert run_ids == {"r0", "r1a", "r1b"}
    # Must have paged through all experiments (5 exps, page size 2 → 3 calls)
    assert len(client.search_experiments_calls) == 3


def test_paginates_runs_multiple_pages():
    """When a single experiment has more runs than the page size, all are fetched."""
    exps = [FakeExperiment("e0", "bigexp")]
    runs = [
        FakeRun(FakeRunInfo(f"r{i}", "e0", f"run{i}", i * 100, i * 200,
                            f"mlflow-artifacts:/e0/r{i}", "FINISHED"), FakeRunData())
        for i in range(6)
    ]
    client = FakeMlflowClient(exps, {"e0": runs})
    mod = fresh_import()
    results = list(mod.iter_runs("fake://uri", client=client))
    assert len(results) == 6
    assert len(client.search_runs_calls) == 3  # 3 pages × 2 runs


def test_neutral_dict_fields_present():
    """Each yielded dict has all required neutral-dict keys."""
    exps = [FakeExperiment("e0", "myexp")]
    run = FakeRun(
        FakeRunInfo("runABC", "e0", "my_run", 5000, 9000,
                    "mlflow-artifacts:/e0/runABC", "FINISHED"),
        FakeRunData(params={"lr": "0.01"}, tags={"env": "prod"}),
    )
    client = FakeMlflowClient(exps, {"e0": [run]})
    mod = fresh_import()
    results = list(mod.iter_runs("fake://uri", client=client))
    assert len(results) == 1
    r = results[0]
    required = {
        "experiment_id", "experiment_name", "run_id", "name", "status",
        "start_time_ms", "end_time_ms", "params", "tags",
        "parent_run_id", "source_commit", "artifact_dir", "artifact_uri",
        "artifact_remote", "datasets", "metrics",
    }
    assert required.issubset(r.keys())
    assert r["experiment_id"] == "e0"
    assert r["experiment_name"] == "myexp"
    assert r["run_id"] == "runABC"
    assert r["name"] == "my_run"
    assert r["status"] == "FINISHED"
    assert r["start_time_ms"] == 5000
    assert r["end_time_ms"] == 9000
    assert r["params"] == {"lr": "0.01"}
    assert r["tags"] == {"env": "prod"}
    assert callable(r["metrics"])


def test_end_time_none_when_run_still_running():
    exps = [FakeExperiment("e0", "e")]
    run = FakeRun(FakeRunInfo("r0", "e0", "r", 1000, None,
                              "mlflow-artifacts:/e0/r0", "RUNNING"), FakeRunData())
    client = FakeMlflowClient(exps, {"e0": [run]})
    mod = fresh_import()
    r = list(mod.iter_runs("fake://uri", client=client))[0]
    assert r["end_time_ms"] is None


def test_metric_history_lazy_and_correct():
    """metrics is a lazy callable; it calls get_metric_history per key."""
    exps = [FakeExperiment("e0", "e")]
    run = FakeRun(
        FakeRunInfo("r0", "e0", "r", 1000, 2000, "mlflow-artifacts:/e0/r0", "FINISHED"),
        FakeRunData(metrics={"loss": 0.5, "acc": 0.9}),
    )
    metric_history = {
        "r0": {
            "loss": [FakeMetric("loss", 0.8, 1000, 0), FakeMetric("loss", 0.5, 2000, 1)],
            "acc": [FakeMetric("acc", 0.9, 2000, 1)],
        }
    }
    client = FakeMlflowClient(exps, {"e0": [run]}, metrics_by_run=metric_history)
    mod = fresh_import()
    # Collecting results does NOT call get_metric_history
    results = list(mod.iter_runs("fake://uri", client=client))
    assert client.get_metric_history_calls == [], "metrics must be lazy"
    # Now invoke the callable
    metric_rows = list(results[0]["metrics"]())
    assert len(metric_rows) == 3
    keys = {row[0] for row in metric_rows}
    assert keys == {"loss", "acc"}
    # Each row is (key, value, timestamp_ms, step)
    loss_rows = sorted([row for row in metric_rows if row[0] == "loss"], key=lambda r: r[3])
    assert loss_rows[0] == ("loss", 0.8, 1000, 0)
    assert loss_rows[1] == ("loss", 0.5, 2000, 1)
    assert client.get_metric_history_calls == [("r0", "loss"), ("r0", "acc")]


def test_parent_run_id_from_tags():
    """parent_run_id is read from mlflow.parentRunId tag."""
    exps = [FakeExperiment("e0", "e")]
    run = FakeRun(
        FakeRunInfo("child", "e0", "child_run", 1000, 2000,
                    "mlflow-artifacts:/e0/child", "FINISHED"),
        FakeRunData(tags={"mlflow.parentRunId": "parent123"}),
    )
    client = FakeMlflowClient(exps, {"e0": [run]})
    mod = fresh_import()
    r = list(mod.iter_runs("fake://uri", client=client))[0]
    assert r["parent_run_id"] == "parent123"


def test_source_commit_from_tags():
    """source_commit is read from mlflow.source.git.commit tag."""
    exps = [FakeExperiment("e0", "e")]
    run = FakeRun(
        FakeRunInfo("r0", "e0", "r", 1000, 2000, "mlflow-artifacts:/e0/r0", "FINISHED"),
        FakeRunData(tags={"mlflow.source.git.commit": "abc123def456"}),
    )
    client = FakeMlflowClient(exps, {"e0": [run]})
    mod = fresh_import()
    r = list(mod.iter_runs("fake://uri", client=client))[0]
    assert r["source_commit"] == "abc123def456"


def test_parent_and_commit_none_when_tags_absent():
    exps = [FakeExperiment("e0", "e")]
    run = FakeRun(FakeRunInfo("r0", "e0", "r", 1000, 2000,
                              "mlflow-artifacts:/e0/r0", "FINISHED"), FakeRunData())
    client = FakeMlflowClient(exps, {"e0": [run]})
    mod = fresh_import()
    r = list(mod.iter_runs("fake://uri", client=client))[0]
    assert r["parent_run_id"] is None
    assert r["source_commit"] is None


def test_deleted_experiments_excluded_by_default():
    """Deleted experiments are skipped when include_deleted=False (default)."""
    exps = [
        FakeExperiment("e0", "active_exp"),
        FakeExperiment("e1", "deleted_exp", lifecycle_stage="deleted"),
    ]
    runs_by_exp = {
        "e0": [FakeRun(FakeRunInfo("r0", "e0", "r0", 1000, 2000,
                                   "mlflow-artifacts:/e0/r0", "FINISHED"), FakeRunData())],
        "e1": [FakeRun(FakeRunInfo("r1", "e1", "r1", 1000, 2000,
                                   "mlflow-artifacts:/e1/r1", "FINISHED"), FakeRunData())],
    }
    client = FakeMlflowClient(exps, runs_by_exp)
    mod = fresh_import()
    results = list(mod.iter_runs("fake://uri", client=client))
    assert {r["run_id"] for r in results} == {"r0"}


def test_deleted_experiments_included_when_flag_set():
    exps = [
        FakeExperiment("e0", "active"),
        FakeExperiment("e1", "deleted", lifecycle_stage="deleted"),
    ]
    runs_by_exp = {
        "e0": [FakeRun(FakeRunInfo("r0", "e0", "r0", 1000, 2000,
                                   "a:/e0/r0", "FINISHED"), FakeRunData())],
        "e1": [FakeRun(FakeRunInfo("r1", "e1", "r1", 1000, 2000,
                                   "a:/e1/r1", "FINISHED"), FakeRunData())],
    }
    client = FakeMlflowClient(exps, runs_by_exp)
    mod = fresh_import()
    results = list(mod.iter_runs("fake://uri", include_deleted=True, client=client))
    assert {r["run_id"] for r in results} == {"r0", "r1"}


def test_experiment_filter_by_name():
    """experiments= list restricts to those experiment names only."""
    exps = [FakeExperiment("e0", "exp_a"), FakeExperiment("e1", "exp_b")]
    runs_by_exp = {
        "e0": [FakeRun(FakeRunInfo("r0", "e0", "r0", 1000, 2000,
                                   "a:/e0/r0", "FINISHED"), FakeRunData())],
        "e1": [FakeRun(FakeRunInfo("r1", "e1", "r1", 1000, 2000,
                                   "a:/e1/r1", "FINISHED"), FakeRunData())],
    }
    client = FakeMlflowClient(exps, runs_by_exp)
    mod = fresh_import()
    results = list(mod.iter_runs("fake://uri", experiments=["exp_a"], client=client))
    assert {r["run_id"] for r in results} == {"r0"}


def test_artifact_remote_flag_for_remote_uri():
    """artifact_remote=True when artifact_uri is a remote store (s3://, gs://, etc.)."""
    exps = [FakeExperiment("e0", "e")]
    run_local = FakeRun(FakeRunInfo("r0", "e0", "r0", 1000, 2000,
                                    "mlflow-artifacts:/e0/r0", "FINISHED"), FakeRunData())
    run_s3 = FakeRun(FakeRunInfo("r1", "e0", "r1", 1000, 2000,
                                  "s3://my-bucket/r1", "FINISHED"), FakeRunData())
    client = FakeMlflowClient(exps, {"e0": [run_local, run_s3]})
    mod = fresh_import()
    results = {r["run_id"]: r for r in mod.iter_runs("fake://uri", client=client)}
    assert results["r0"]["artifact_remote"] is False
    assert results["r1"]["artifact_remote"] is True


def test_download_artifacts_helper(tmp_path):
    """download_artifacts(run_id, dest) delegates to client.download_artifacts."""
    exps = [FakeExperiment("e0", "e")]
    client = FakeMlflowClient(exps, {})
    mod = fresh_import()
    dest = str(tmp_path / "dl")
    mod.download_artifacts(client, "runXYZ", dest)
    assert client.download_artifacts_calls == [("runXYZ", "", dest)]


def test_missing_mlflow_raises_import_error_with_hint(monkeypatch):
    """When mlflow is not installed, ImportError is raised with install hint."""
    # Remove any cached module
    for key in list(sys.modules):
        if key == MODULE or key.startswith(MODULE + ".") or key == "mlflow" or key.startswith("mlflow."):
            del sys.modules[key]

    original_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def mock_import(name, *args, **kwargs):
        if name == "mlflow" or name.startswith("mlflow."):
            raise ImportError("No module named 'mlflow'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", mock_import)

    # Force reimport with patched import
    for key in list(sys.modules):
        if key == MODULE or key.startswith(MODULE + "."):
            del sys.modules[key]

    mod = importlib.import_module(MODULE)
    with pytest.raises(ImportError, match=r'pip install.*vmn\[mlflow\]'):
        list(mod.iter_runs("fake://uri"))


def test_client_created_from_tracking_uri_when_not_provided(monkeypatch):
    """When client=None, a real MlflowClient is created using tracking_uri."""
    # Build a minimal fake mlflow module
    fake_mlflow = types.ModuleType("mlflow")
    fake_tracking = types.ModuleType("mlflow.tracking")

    created_uris = []

    class FakeClientClass:
        def __init__(self, tracking_uri):
            created_uris.append(tracking_uri)
            # Return something iterable with empty results
            self._experiments = []

        def search_experiments(self, view_type=None, page_token=None, max_results=1000):
            return FakePage([])

        def search_runs(self, experiment_ids, page_token=None, run_view_type=None,
                        max_results=1000):
            return FakePage([])

    fake_tracking.MlflowClient = FakeClientClass
    fake_mlflow.tracking = fake_tracking

    # Inject fakes
    sys.modules["mlflow"] = fake_mlflow
    sys.modules["mlflow.tracking"] = fake_tracking

    for key in list(sys.modules):
        if key == MODULE or key.startswith(MODULE + "."):
            del sys.modules[key]

    mod = importlib.import_module(MODULE)
    list(mod.iter_runs("my://tracking/uri"))
    assert "my://tracking/uri" in created_uris

    # Cleanup
    for key in ["mlflow", "mlflow.tracking"]:
        sys.modules.pop(key, None)
