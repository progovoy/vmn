"""
Read an MLflow ``mlruns/`` FileStore directory without requiring mlflow.

Public API::

    iter_runs(mlruns_path, experiments=None, include_deleted=False)
        -> Iterator[NeutralRun]

Each yielded dict (NeutralRun) contains::

    experiment_id   str
    experiment_name str
    run_id          str
    name            str
    status          str  -- 'FINISHED'|'FAILED'|'KILLED'|'RUNNING'|'SCHEDULED'
    start_time_ms   int
    end_time_ms     int|None
    params          dict[str, str]
    tags            dict[str, str]  -- all tags, including mlflow.*
    parent_run_id   str|None
    source_commit   str|None
    artifact_dir    str|None  -- local fs path when uri is local, else None
    artifact_uri    str
    artifact_remote bool
    datasets        list[dict]
    metrics         callable() -> Iterator[(key, value, timestamp_ms, step)]

Malformed files emit a logging.WARNING and are skipped; they never raise.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set

import yaml

# MLflow RunStatus int → str mapping (from mlflow.entities.RunStatus source)
_INT_STATUS: Dict[int, str] = {
    1: "RUNNING",
    2: "SCHEDULED",
    3: "FINISHED",
    4: "FAILED",
    5: "KILLED",
}
_VALID_STATUSES: Set[str] = set(_INT_STATUS.values())

log = logging.getLogger(__name__)


def _read_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """Read and parse a YAML file with yaml.safe_load; return None on any error."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("mlflow_filestore: cannot read %s: %s", path, exc)
        return None
    try:
        result = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        log.warning("mlflow_filestore: malformed YAML %s: %s", path, exc)
        return None
    if not isinstance(result, dict):
        log.warning("mlflow_filestore: unexpected YAML structure in %s", path)
        return None
    return result


# ---------------------------------------------------------------------------
# Status normalisation
# ---------------------------------------------------------------------------

def _normalise_status(raw: Any) -> str:
    if isinstance(raw, int):
        return _INT_STATUS.get(raw, "RUNNING")
    s = str(raw).upper().strip()
    if s in _VALID_STATUSES:
        return s
    # Try integer stored as string
    try:
        return _INT_STATUS.get(int(s), "RUNNING")
    except (ValueError, TypeError):
        pass
    return "RUNNING"


# ---------------------------------------------------------------------------
# Artifact helpers
# ---------------------------------------------------------------------------

def _is_remote_uri(uri: str) -> bool:
    """Return True when the artifact URI is a remote scheme (s3://, gs://, etc.)."""
    if not uri:
        return False
    lower = uri.lower()
    remote_schemes = ("s3://", "gs://", "azureml://", "wasbs://", "hdfs://",
                      "dbfs://", "http://", "https://", "ftp://")
    return any(lower.startswith(s) for s in remote_schemes)


def _local_path_from_uri(uri: str) -> Optional[str]:
    """Return a local filesystem path for a file:// or bare-path URI, or None."""
    if not uri:
        return None
    if uri.lower().startswith("file://"):
        path = uri[7:]
        # Handle file:///abs/path → /abs/path
        if path.startswith("//"):
            path = path[1:]
        return path
    if _is_remote_uri(uri):
        return None
    return uri


# ---------------------------------------------------------------------------
# Tag / param / metric readers
# ---------------------------------------------------------------------------

def _read_flat_dir(dir_path: Path) -> Dict[str, str]:
    """
    Read a ``params/`` or ``tags/`` directory.

    File names are the keys (which may contain '/' represented as nested
    subdirectories).  File contents are the values.
    """
    result: Dict[str, str] = {}
    if not dir_path.is_dir():
        return result
    for item in dir_path.rglob("*"):
        if item.is_file():
            rel = item.relative_to(dir_path)
            key = rel.as_posix()  # restores '/' separators from subdirs
            try:
                value = item.read_text(encoding="utf-8", errors="replace").strip()
            except OSError as exc:
                log.warning(
                    "mlflow_filestore: cannot read %s: %s", item, exc
                )
                continue
            result[key] = value
    return result


def _make_metrics_callable(
    metrics_dir: Path,
) -> Callable[[], Iterator[tuple]]:
    """Return a zero-argument callable that lazily streams metric rows."""

    def _iter() -> Iterator[tuple]:
        if not metrics_dir.is_dir():
            return
        for metric_file in sorted(metrics_dir.iterdir()):
            if not metric_file.is_file():
                continue
            key = metric_file.name
            try:
                text = metric_file.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                log.warning(
                    "mlflow_filestore: cannot read metric %s: %s",
                    metric_file,
                    exc,
                )
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    log.warning(
                        "mlflow_filestore: malformed metric line in %s:%d: %r",
                        metric_file,
                        lineno,
                        line,
                    )
                    continue
                try:
                    ts = int(parts[0])
                    val = float(parts[1])
                    step = int(parts[2]) if len(parts) >= 3 else 0
                except (ValueError, IndexError):
                    log.warning(
                        "mlflow_filestore: parse error in metric %s:%d: %r",
                        metric_file,
                        lineno,
                        line,
                    )
                    continue
                yield key, val, ts, step

    return _iter


# ---------------------------------------------------------------------------
# Dataset (inputs) reader (mlflow >= 2.4)
# ---------------------------------------------------------------------------

def _read_datasets(run_dir: Path) -> List[Dict[str, Any]]:
    """
    Read the ``inputs/dataset_inputs/`` subtree.

    Each entry dir contains a ``meta.yaml`` with ``dataset`` and ``tags`` keys.
    Returns an empty list when the directory is absent or unreadable.
    """
    datasets: List[Dict[str, Any]] = []
    inputs_dir = run_dir / "inputs" / "dataset_inputs"
    if not inputs_dir.is_dir():
        return datasets
    for entry in inputs_dir.iterdir():
        if not entry.is_dir():
            continue
        meta_path = entry / "meta.yaml"
        meta = _read_yaml(meta_path)
        if meta is None:
            continue
        ds_block = meta.get("dataset")
        if not isinstance(ds_block, dict):
            continue
        record: Dict[str, Any] = {
            "name": ds_block.get("name", ""),
            "digest": ds_block.get("digest", ""),
            "source_type": ds_block.get("source_type", ""),
            "source": ds_block.get("source", ""),
        }
        datasets.append(record)
    return datasets


# ---------------------------------------------------------------------------
# Core readers
# ---------------------------------------------------------------------------

def _read_run(
    run_dir: Path,
    exp_id: str,
    exp_name: str,
) -> Optional[Dict[str, Any]]:
    """Build a neutral run dict from a run directory.  Returns None on error."""
    meta_path = run_dir / "meta.yaml"
    meta = _read_yaml(meta_path)
    if meta is None:
        log.warning(
            "mlflow_filestore: skipping run dir %s (bad or missing meta.yaml)",
            run_dir,
        )
        return None

    run_id = str(meta.get("run_id") or meta.get("run_uuid") or "")
    if not run_id:
        log.warning(
            "mlflow_filestore: skipping run dir %s (no run_id)", run_dir
        )
        return None

    start_time = meta.get("start_time", 0) or 0
    end_raw = meta.get("end_time", 0) or 0
    end_time: Optional[int] = int(end_raw) if end_raw and int(end_raw) > 0 else None

    artifact_uri = str(meta.get("artifact_uri") or "")
    if not artifact_uri:
        artifact_uri = str(run_dir / "artifacts")
    artifact_remote = _is_remote_uri(artifact_uri)
    artifact_dir = _local_path_from_uri(artifact_uri) if not artifact_remote else None

    tags = _read_flat_dir(run_dir / "tags")
    params = _read_flat_dir(run_dir / "params")
    metrics_callable = _make_metrics_callable(run_dir / "metrics")
    datasets = _read_datasets(run_dir)

    # Derive name: prefer run_name field, then mlflow.runName tag
    name = str(meta.get("run_name") or tags.get("mlflow.runName") or "")
    parent_run_id: Optional[str] = tags.get("mlflow.parentRunId") or None
    source_commit: Optional[str] = tags.get("mlflow.source.git.commit") or None
    status = _normalise_status(meta.get("status", "RUNNING"))

    return {
        "experiment_id": exp_id,
        "experiment_name": exp_name,
        "run_id": run_id,
        "name": name,
        "status": status,
        "start_time_ms": int(start_time),
        "end_time_ms": end_time,
        "params": params,
        "tags": tags,
        "parent_run_id": parent_run_id,
        "source_commit": source_commit,
        "artifact_dir": artifact_dir,
        "artifact_uri": artifact_uri,
        "artifact_remote": artifact_remote,
        "datasets": datasets,
        "metrics": metrics_callable,
        "_lifecycle_stage": str(meta.get("lifecycle_stage", "active")),
    }


def _read_experiment_runs(
    exp_dir: Path,
    exp_id: str,
    exp_name: str,
    include_deleted: bool,
) -> Iterator[Dict[str, Any]]:
    """Yield run dicts from a single experiment directory."""
    for item in exp_dir.iterdir():
        # Skip files, meta.yaml, .trash dir
        if item.name in ("meta.yaml",) or not item.is_dir():
            continue
        if item.name.startswith("."):
            continue  # skip .trash and hidden dirs

        run = _read_run(item, exp_id, exp_name)
        if run is None:
            continue

        lifecycle = run.pop("_lifecycle_stage", "active")
        if lifecycle != "active" and not include_deleted:
            continue

        yield run


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def iter_runs(
    mlruns_path: "str | Path",
    experiments: Optional[List[str]] = None,
    include_deleted: bool = False,
) -> Iterator[Dict[str, Any]]:
    """
    Iterate neutral run dicts from an MLflow FileStore ``mlruns/`` directory.

    Parameters
    ----------
    mlruns_path:
        Path to the ``mlruns/`` directory (the directory that contains
        numbered experiment subdirectories).
    experiments:
        Optional list of experiment names *or* experiment IDs to include.
        When ``None`` (default) all experiments are included.
    include_deleted:
        When ``True``, runs with ``lifecycle_stage=deleted`` are included.
        Runs inside ``.trash/`` are always skipped.
    """
    root = Path(mlruns_path)
    if not root.is_dir():
        log.warning("mlflow_filestore: mlruns path %s is not a directory", root)
        return

    # Build a filter set from the experiments parameter
    filter_names: Optional[Set[str]] = None
    filter_ids: Optional[Set[str]] = None
    if experiments is not None:
        filter_names = set()
        filter_ids = set()
        for e in experiments:
            # Treat purely numeric strings as IDs, otherwise names
            if str(e).isdigit():
                filter_ids.add(str(e))
            else:
                filter_names.add(str(e))

    for exp_dir in sorted(root.iterdir()):
        if not exp_dir.is_dir():
            continue
        if exp_dir.name.startswith("."):
            continue
        if not exp_dir.name.isdigit():
            # Experiment dirs are named with integer IDs; skip non-numeric
            continue

        exp_id = exp_dir.name
        meta_path = exp_dir / "meta.yaml"
        exp_meta = _read_yaml(meta_path) or {}
        exp_name = str(exp_meta.get("name") or exp_id)
        exp_lifecycle = str(exp_meta.get("lifecycle_stage", "active"))

        if exp_lifecycle != "active" and not include_deleted:
            continue

        # Apply experiment filter
        if filter_names is not None or filter_ids is not None:
            matched = False
            if filter_ids and exp_id in filter_ids:
                matched = True
            if filter_names and exp_name in filter_names:
                matched = True
            if not matched:
                continue

        yield from _read_experiment_runs(
            exp_dir, exp_id, exp_name, include_deleted
        )
