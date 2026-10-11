"""
MLflow FileStore's dataset-input layout (mlflow >= 2.4, unchanged through 3.x), with
the meta.yaml shapes copied from a tree ``mlflow.log_input`` wrote::

    <exp>/datasets/<md5(name + digest)>/meta.yaml        the Dataset fields
    <exp>/<run>/inputs/<md5(source_id + run_id)>/meta.yaml
        {source_type: DATASET | MODEL, source_id, destination_type: RUN,
         destination_id, tags}

MLflow writes ``destination_id`` as the source id, not the run id.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

import yaml


def _md5(*parts: str) -> str:
    digest = hashlib.md5()
    for part in parts:
        digest.update(part.encode("utf-8"))
    return digest.hexdigest()


def _write_meta(directory: Path, data: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "meta.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def _write_input(exp_dir: Path, run_id: str, source_type: str, source_id: str,
                 tags: dict[str, str]) -> None:
    _write_meta(exp_dir / run_id / "inputs" / _md5(source_id, run_id),
                {"destination_id": source_id, "destination_type": "RUN",
                 "source_id": source_id, "source_type": source_type, "tags": tags})


def dataset_id(dataset: dict[str, str]) -> str:
    """The folder name MLflow gives *dataset* under ``<exp>/datasets/``."""
    return _md5(dataset["name"], dataset["digest"])


def log_dataset_inputs(exp_dir: str | Path, run_id: str,
                       datasets: Iterable[dict[str, str]],
                       context: str = "training") -> None:
    """Write *datasets* (name/digest/source_type/source dicts) as the run's inputs."""
    exp_dir = Path(exp_dir)
    for dataset in datasets:
        _write_meta(exp_dir / "datasets" / dataset_id(dataset),
                    {"profile": '{"num_rows": 3, "num_elements": 6}', "schema": None,
                     **dataset})
        _write_input(exp_dir, run_id, "DATASET", dataset_id(dataset),
                     {"mlflow.data.context": context})


def log_model_input(exp_dir: str | Path, run_id: str, model_id: str) -> None:
    """A logged-model input (mlflow 3): an ``inputs/`` entry that is no dataset."""
    _write_input(Path(exp_dir), run_id, "MODEL", model_id, {})
