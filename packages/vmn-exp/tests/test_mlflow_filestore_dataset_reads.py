"""``--mlruns`` parses each of an experiment's datasets once, however many
of its runs used it; every run still lists it as its own input."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mlflow_dataset_layout import dataset_id, log_dataset_inputs
from mlflow_fixtures import MlflowFixtureBuilder
from vmn_exp.importers import mlflow_filestore

TRAIN = {"name": "train", "digest": "244437a9", "source_type": "local",
         "source": '{"uri": "/data/train.csv"}'}
RUNS = ["a" * 32, "b" * 32, "c" * 32]


def test_runs_sharing_a_dataset_parse_its_meta_once(tmp_path, monkeypatch):
    mlruns = tmp_path / "mlruns"
    builder = MlflowFixtureBuilder(mlruns)
    builder.add_experiment("1", "exp_one")
    for run_id in RUNS:
        builder.add_run("1", run_id)
        log_dataset_inputs(mlruns / "1", run_id, [TRAIN])
    dataset_meta = mlruns / "1" / "datasets" / dataset_id(TRAIN) / "meta.yaml"
    reads = []
    real = mlflow_filestore._read_yaml

    def counting(path):
        if path == dataset_meta:
            reads.append(path)
        return real(path)

    monkeypatch.setattr(mlflow_filestore, "_read_yaml", counting)

    runs = list(mlflow_filestore.iter_runs(mlruns))

    assert sorted(run["run_id"] for run in runs) == RUNS
    assert all(run["datasets"] == [TRAIN] for run in runs)
    assert len(reads) == 1
    runs[0]["datasets"][0]["name"] = "changed"
    assert runs[1]["datasets"] == [TRAIN]
