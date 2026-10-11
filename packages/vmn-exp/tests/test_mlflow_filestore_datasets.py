"""``--mlruns`` reads dataset inputs in MLflow FileStore's real layout (the experiment's
``datasets/`` folder, joined through the run's ``inputs/`` entries), so FileStore and
tracking-server imports of the same runs record the same inputs.
"""
from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

from mlflow_dataset_layout import dataset_id, log_dataset_inputs, log_model_input
from mlflow_fixtures import MlflowFixtureBuilder
from vmn_exp.importers import mlflow_client, mlflow_filestore
from vmn_exp.importers.import_records import import_run, run_verstr
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "myapp"
RUN_ID = "7c451dc10bdd4facb5741345edeaa8d8"
TRAIN = {"name": "train", "digest": "244437a9", "source_type": "local",
         "source": '{"uri": "/data/train.csv"}'}
EVAL = {"name": "evalset", "digest": "5edc214a", "source_type": "s3",
        "source": '{"uri": "s3://bucket/eval.npy"}'}


def _mlruns(tmp_path, *datasets):
    mlruns = tmp_path / "mlruns"
    builder = MlflowFixtureBuilder(mlruns)
    builder.add_experiment("1", "exp_one")
    builder.add_run("1", RUN_ID)
    log_dataset_inputs(mlruns / "1", RUN_ID, datasets)
    return mlruns


def _by_name(items):
    return sorted(items, key=lambda item: item["name"])


def _filestore_run(mlruns):
    [run] = mlflow_filestore.iter_runs(mlruns)
    return run


def test_dataset_inputs_are_read_from_the_experiment_datasets_folder(tmp_path):
    run = _filestore_run(_mlruns(tmp_path, TRAIN, EVAL))

    assert _by_name(run["datasets"]) == [EVAL, TRAIN]


def test_model_inputs_and_inputs_of_a_missing_dataset_are_no_datasets(tmp_path):
    mlruns = _mlruns(tmp_path, TRAIN, EVAL)
    log_model_input(mlruns / "1", RUN_ID, "m-0a1b2c")
    shutil.rmtree(mlruns / "1" / "datasets" / dataset_id(EVAL))

    assert _filestore_run(mlruns)["datasets"] == [TRAIN]


def test_reserved_experiment_folders_are_not_read_as_runs(tmp_path, caplog):
    mlruns = _mlruns(tmp_path, TRAIN)
    (mlruns / "1" / "tags").mkdir()
    (mlruns / "1" / "tags" / "team").write_text("vision", encoding="utf-8")
    for folder in ("traces", "models"):
        (mlruns / "1" / folder / "x1").mkdir(parents=True)

    with caplog.at_level(logging.WARNING, logger=mlflow_filestore.__name__):
        runs = list(mlflow_filestore.iter_runs(mlruns))

    assert [run["run_id"] for run in runs] == [RUN_ID]
    assert [record.getMessage() for record in caplog.records] == []


class _Client:
    """The MlflowClient calls the importer makes, for one experiment."""

    def __init__(self, run):
        self._run = run

    def search_experiments(self, view_type=None, page_token=None):
        return [SimpleNamespace(experiment_id="1", name="exp_one")]

    def search_runs(self, experiment_ids, page_token=None, run_view_type=None):
        return [self._run]

    def get_metric_history(self, run_id, key):
        return []


def _client_run(*datasets):
    """The run as ``MlflowClient.get_run`` returns it for the same FileStore tree."""
    info = SimpleNamespace(run_id=RUN_ID, experiment_id="1", run_name="",
                           start_time=1700000000000, end_time=1700000060000,
                           artifact_uri="file:///mlruns/1/artifacts", status="FINISHED")
    inputs = SimpleNamespace(dataset_inputs=[
        SimpleNamespace(dataset=SimpleNamespace(schema=None, profile="{}", **dataset),
                        tags=[SimpleNamespace(key="mlflow.data.context", value="training")])
        for dataset in datasets])
    data = SimpleNamespace(params={}, tags={}, metrics={})
    [run] = mlflow_client.iter_runs("fake://", client=_Client(
        SimpleNamespace(info=info, data=data, inputs=inputs)))
    return run


def _inputs(storage):
    return _by_name({k: v for k, v in entry.items() if k not in ("timestamp", "ts")}
                    for entry in storage.load_merged_log(APP, run_verstr(RUN_ID))
                    if entry.get("type") == "input")


def test_client_and_filestore_imports_of_the_real_layout_record_equal_inputs(tmp_path):
    from_files = LocalSnapshotStorage(str(tmp_path / "files"), area="runs")
    import_run(from_files, APP, _filestore_run(_mlruns(tmp_path, TRAIN, EVAL)))
    from_client = LocalSnapshotStorage(str(tmp_path / "client"), area="runs")
    import_run(from_client, APP, _client_run(TRAIN, EVAL))

    assert _inputs(from_files) == _inputs(from_client)
    assert [entry["name"] for entry in _inputs(from_files)] == ["evalset", "train"]
