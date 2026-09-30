"""
Builder for MLflow FileStore test fixtures.

Creates a minimal mlruns/ directory tree that matches the layout written by
MLflow's FileStore backend so that mlflow_filestore.py can be tested without
installing mlflow itself.

Usage::

    builder = MlflowFixtureBuilder(tmp_path)
    builder.add_experiment("1", "my_exp")
    run = builder.add_run(
        exp_id="1",
        run_id="abc123" * 5,  # 30-char fake UUID
        name="run1",
        status="FINISHED",
        start_time=1700000000000,
        end_time=1700000060000,
        params={"lr": "0.01"},
        tags={"my/nested/key": "value"},
        metrics={"loss": [(1700000001000, 0.5, 0), (1700000002000, 0.3, 1)]},
    )
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _yaml_str(d: Dict[str, Any]) -> str:
    """Minimal YAML serializer – handles str, int, None, bool scalars only."""
    lines = []
    for k, v in d.items():
        if v is None:
            lines.append(f"{k}: null")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, int):
            lines.append(f"{k}: {v}")
        else:
            # Quote strings that YAML would otherwise misparse
            safe = str(v).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k}: "{safe}"')
    return "\n".join(lines) + "\n"


class MlflowFixtureBuilder:
    """Write a synthetic MLflow FileStore tree under *root*."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Experiments
    # ------------------------------------------------------------------

    def add_experiment(
        self,
        exp_id: str,
        name: str,
        lifecycle_stage: str = "active",
        artifact_location: Optional[str] = None,
    ) -> "MlflowFixtureBuilder":
        exp_dir = self.root / exp_id
        exp_dir.mkdir(exist_ok=True)
        loc = artifact_location or str(exp_dir)
        _write(
            exp_dir / "meta.yaml",
            _yaml_str(
                {
                    "artifact_location": loc,
                    "experiment_id": exp_id,
                    "lifecycle_stage": lifecycle_stage,
                    "name": name,
                }
            ),
        )
        return self

    def add_deleted_experiment(
        self, exp_id: str, name: str
    ) -> "MlflowFixtureBuilder":
        return self.add_experiment(exp_id, name, lifecycle_stage="deleted")

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def add_run(
        self,
        exp_id: str,
        run_id: str,
        *,
        name: str = "",
        status: Any = "FINISHED",
        start_time: int = 1700000000000,
        end_time: Optional[int] = 1700000060000,
        lifecycle_stage: str = "active",
        artifact_uri: Optional[str] = None,
        user_id: str = "test-user",
        params: Optional[Dict[str, str]] = None,
        metrics: Optional[Dict[str, Sequence[Tuple[int, float, int]]]] = None,
        tags: Optional[Dict[str, str]] = None,
        datasets: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Create a run directory; returns *run_id* for chaining."""
        run_dir = self.root / exp_id / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        uri = artifact_uri or str(run_dir / "artifacts")
        meta: Dict[str, Any] = {
            "artifact_uri": uri,
            "end_time": end_time if end_time is not None else 0,
            "experiment_id": exp_id,
            "lifecycle_stage": lifecycle_stage,
            "run_id": run_id,
            "run_name": name,
            "run_uuid": run_id,
            "start_time": start_time,
            "status": status,
            "user_id": user_id,
        }
        _write(run_dir / "meta.yaml", _yaml_str(meta))

        # params
        if params:
            for key, val in params.items():
                _write(run_dir / "params" / key, str(val))

        # tags (supports nested keys via '/')
        all_tags: Dict[str, str] = {}
        if name:
            all_tags["mlflow.runName"] = name
        if tags:
            all_tags.update(tags)
        for key, val in all_tags.items():
            _write(run_dir / "tags" / key, str(val))

        # metrics: each key → file with lines "<ts> <value> <step>"
        if metrics:
            for key, rows in metrics.items():
                lines = []
                for row in rows:
                    if len(row) == 3:
                        ts, val, step = row
                        lines.append(f"{ts} {val} {step}")
                    else:
                        ts, val = row[:2]
                        lines.append(f"{ts} {val}")
                _write(run_dir / "metrics" / key, "\n".join(lines) + "\n")

        # datasets (mlflow >= 2.4 inputs dir layout)
        if datasets:
            self._write_datasets(run_dir, datasets)

        return run_id

    def add_deleted_run(
        self,
        exp_id: str,
        run_id: str,
        **kwargs: Any,
    ) -> str:
        """Add a run with lifecycle_stage='deleted' (or write it to .trash)."""
        kwargs["lifecycle_stage"] = "deleted"
        return self.add_run(exp_id, run_id, **kwargs)

    def add_trashed_run(
        self,
        exp_id: str,
        run_id: str,
        **kwargs: Any,
    ) -> str:
        """Write the run under <exp_id>/.trash/<run_id> with deleted stage."""
        trash_dir = self.root / exp_id / ".trash"
        trash_dir.mkdir(parents=True, exist_ok=True)

        # temporarily override run_dir by adjusting the builder path
        orig_root = self.root
        # We build into a temporary exp dir called ".trash" under orig_root
        trash_builder = MlflowFixtureBuilder(self.root / exp_id / ".trash")
        # But we need the run inside trash, not under exp_id again
        trash_builder.root = self.root / exp_id / ".trash"
        trash_builder.root.mkdir(parents=True, exist_ok=True)
        kwargs.setdefault("lifecycle_stage", "deleted")
        # write directly
        run_dir = trash_builder.root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        uri = kwargs.get("artifact_uri") or str(run_dir / "artifacts")
        meta: Dict[str, Any] = {
            "artifact_uri": uri,
            "end_time": kwargs.get("end_time", 1700000060000) or 0,
            "experiment_id": exp_id,
            "lifecycle_stage": "deleted",
            "run_id": run_id,
            "run_name": kwargs.get("name", ""),
            "run_uuid": run_id,
            "start_time": kwargs.get("start_time", 1700000000000),
            "status": kwargs.get("status", "FINISHED"),
            "user_id": kwargs.get("user_id", "test-user"),
        }
        _write(run_dir / "meta.yaml", _yaml_str(meta))
        return run_id

    def _write_datasets(
        self, run_dir: Path, datasets: List[Dict[str, Any]]
    ) -> None:
        """Write mlflow>=2.4 inputs/dataset_inputs/ layout."""
        for ds in datasets:
            name = ds.get("name", "dataset")
            digest = ds.get("digest", "abc123")
            folder_name = f"{name}_{digest}"
            ds_dir = run_dir / "inputs" / "dataset_inputs" / folder_name
            ds_dir.mkdir(parents=True, exist_ok=True)
            meta = {
                "dataset": {
                    "name": name,
                    "digest": digest,
                    "source_type": ds.get("source_type", "local"),
                    "source": ds.get("source", ""),
                    "schema": ds.get("schema"),
                    "profile": ds.get("profile"),
                },
                "tags": ds.get("tags", []),
            }
            # Write a simplified YAML-like structure
            lines = ["dataset:"]
            for k, v in meta["dataset"].items():
                if v is None:
                    lines.append(f"  {k}: null")
                else:
                    lines.append(f'  {k}: "{v}"')
            lines.append("tags: []")
            _write(ds_dir / "meta.yaml", "\n".join(lines) + "\n")
