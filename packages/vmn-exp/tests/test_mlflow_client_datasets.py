"""The tracking-server importer reads a run's dataset inputs
(``run.inputs.dataset_inputs``) like the FileStore reader does, so
``--tracking-uri`` imports carry the same input entries as ``--mlruns`` ones.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

from mlflow_fixtures import MlflowFixtureBuilder
from vmn_exp.importers import mlflow_client, mlflow_filestore
from vmn_exp.importers.import_records import import_run, run_verstr
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "myapp"
RUN_ID = "d" * 32
DATASET = {"name": "imagenet", "digest": "9f2c1e", "source_type": "s3",
           "source": "s3://bucket/imagenet"}


class _Client:
    """The MlflowClient calls the importer makes, for one experiment."""

    def __init__(self, runs):
        self._runs = runs

    def search_experiments(self, view_type=None, page_token=None):
        return [SimpleNamespace(experiment_id="1", name="exp_one")]

    def search_runs(self, experiment_ids, page_token=None, run_view_type=None):
        return list(self._runs)

    def get_metric_history(self, run_id, key):
        return []


def _client_run(inputs=None, tags=None, **extra):
    info = SimpleNamespace(run_id=RUN_ID, experiment_id="1", run_name="r",
                           start_time=1700000000000, end_time=1700000060000,
                           artifact_uri="s3://art/1", status="FINISHED")
    data = SimpleNamespace(params={}, tags=dict(tags or {}), metrics={})
    return SimpleNamespace(info=info, data=data, inputs=inputs, **extra)


def _dataset_inputs(*datasets):
    return SimpleNamespace(dataset_inputs=[
        SimpleNamespace(dataset=SimpleNamespace(schema=None, profile=None, **ds), tags=[])
        for ds in datasets])


def _client_runs(run):
    return list(mlflow_client.iter_runs("fake://", client=_Client([run])))


def test_a_client_run_carries_its_dataset_inputs():
    [run] = _client_runs(_client_run(inputs=_dataset_inputs(DATASET)))

    assert run["datasets"] == [DATASET]


def test_a_client_run_without_inputs_has_no_datasets():
    assert _client_runs(_client_run(inputs=None))[0]["datasets"] == []
    assert _client_runs(_client_run(inputs=SimpleNamespace(dataset_inputs=None)))[0][
        "datasets"] == []
    bare = SimpleNamespace(info=_client_run().info, data=_client_run().data)
    assert _client_runs(bare)[0]["datasets"] == []


def test_missing_dataset_fields_read_as_empty_strings():
    [run] = _client_runs(_client_run(inputs=SimpleNamespace(dataset_inputs=[
        SimpleNamespace(dataset=SimpleNamespace(name="tiny"))])))

    assert run["datasets"] == [{"name": "tiny", "digest": "", "source_type": "",
                                "source": ""}]


def _inputs(storage):
    return [{k: v for k, v in e.items() if k not in ("timestamp", "ts")}
            for e in storage.load_merged_log(APP, run_verstr(RUN_ID))
            if e.get("type") == "input"]


def test_client_and_filestore_imports_record_the_same_inputs(tmp_path):
    mlruns = tmp_path / "mlruns"
    builder = MlflowFixtureBuilder(mlruns)
    builder.add_experiment("1", "exp_one")
    builder.add_run("1", RUN_ID, datasets=[DATASET])
    from_files = LocalSnapshotStorage(str(tmp_path / "files"), area="runs")
    import_run(from_files, APP, next(mlflow_filestore.iter_runs(mlruns)))

    from_client = LocalSnapshotStorage(str(tmp_path / "client"), area="runs")
    [run] = _client_runs(_client_run(inputs=_dataset_inputs(DATASET)))
    import_run(from_client, APP, run)

    assert _inputs(from_client) == _inputs(from_files) != []


def test_a_client_import_maps_the_mlflow_tags(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    [run] = _client_runs(_client_run(tags={"mlflow.user": "carol@acme.io",
                                           "mlflow.note.content": "baseline"}))

    import_run(storage, APP, run)

    verstr = run_verstr(RUN_ID)
    assert storage.load_metadata(APP, verstr)["note"] == "baseline"
    [entry] = [e for e in storage.load_merged_log(APP, verstr) if e["type"] == "features"]
    assert entry["author"] == {"git_user_email": "carol@acme.io", "source": "mlflow"}
