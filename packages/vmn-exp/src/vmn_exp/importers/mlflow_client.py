"""MLflow tracking-server importer for vmn_exp.

Reads runs from an MLflow tracking server via ``mlflow.tracking.MlflowClient``
and yields neutral run dicts compatible with the vmn_exp importer contract.

Optional dependency: ``mlflow-skinny`` (or full ``mlflow``).
Install hint: ``pip install "vmn-exp[mlflow]"``
"""

from __future__ import annotations

import os
from typing import Callable, Dict, Iterator, List, Optional

from vmn_exp.importers._utils import is_remote_uri


# ---------------------------------------------------------------------------
# Lazy mlflow import
# ---------------------------------------------------------------------------

def _import_mlflow_client():
    """Lazily import MlflowClient; raise a friendly ImportError if mlflow absent."""
    try:
        import mlflow.tracking  # noqa: PLC0415
        return mlflow.tracking.MlflowClient
    except ImportError as exc:
        raise ImportError(
            "mlflow is required for this importer. "
            'Install it with: pip install "vmn-exp[mlflow]"'
        ) from exc


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def _iter_pages(call_fn: Callable):
    """Page through any MLflow paginated API, yielding all items."""
    page_token = None
    while True:
        page = call_fn(page_token)
        yield from page
        page_token = getattr(page, "token", None)
        if not page_token:
            break


def _iter_pages_experiments(client, include_deleted: bool):
    """Yield all Experiment objects, paging through search_experiments."""
    # view_type strings from mlflow.entities.ViewType (passed as strings to
    # avoid importing the enum from an optional dependency).
    view_type = "ALL" if include_deleted else "ACTIVE_ONLY"
    yield from _iter_pages(
        lambda token: client.search_experiments(view_type=view_type, page_token=token)
    )


def _iter_pages_runs(client, experiment_ids: List[str], include_deleted: bool):
    """Yield all Run objects for *experiment_ids*, paging through search_runs."""
    run_view_type = "ALL" if include_deleted else "ACTIVE_ONLY"
    yield from _iter_pages(
        lambda token: client.search_runs(
            experiment_ids=experiment_ids,
            page_token=token,
            run_view_type=run_view_type,
        )
    )


# ---------------------------------------------------------------------------
# Neutral-dict builder
# ---------------------------------------------------------------------------

def _build_run_dict(run, experiment_name: str, client) -> dict:
    info = run.info
    data = run.data
    tags: Dict[str, str] = dict(data.tags) if data.tags else {}

    artifact_uri: str = info.artifact_uri or ""
    # mlflow stores end_time=0 for still-running runs; normalise to None.
    end_time_ms = getattr(info, "end_time", None) or None
    metric_keys = list(data.metrics.keys()) if data.metrics else []
    run_id = info.run_id

    def _metrics() -> Iterator:
        for key in metric_keys:
            for m in client.get_metric_history(run_id, key):
                yield (m.key, m.value, m.timestamp, m.step)

    return {
        "experiment_id": info.experiment_id,
        "experiment_name": experiment_name,
        "run_id": run_id,
        "name": info.run_name or "",
        "status": info.status,
        "start_time_ms": info.start_time,
        "end_time_ms": end_time_ms,
        "params": dict(data.params) if data.params else {},
        "tags": tags,
        "parent_run_id": tags.get("mlflow.parentRunId"),
        "source_commit": tags.get("mlflow.source.git.commit"),
        "artifact_dir": None,
        "artifact_uri": artifact_uri,
        "artifact_remote": is_remote_uri(artifact_uri),
        "datasets": [],
        "metrics": _metrics,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def iter_runs(
    tracking_uri: str,
    experiments: Optional[List[str]] = None,
    include_deleted: bool = False,
    client=None,
) -> Iterator[dict]:
    """Yield neutral run dicts from an MLflow tracking server.

    Parameters
    ----------
    tracking_uri:
        URI of the MLflow tracking server (e.g. ``http://localhost:5000``).
    experiments:
        Optional list of experiment *names* to restrict to. When ``None``,
        all experiments are imported.
    include_deleted:
        When ``True``, also yield runs from deleted experiments and deleted
        runs. Default ``False``.
    client:
        An existing ``MlflowClient`` instance to use. When ``None`` (default),
        a new client is created from *tracking_uri*.  Primarily useful for
        testing with a fake client.

    Yields
    ------
    dict
        Neutral run dict with keys: experiment_id, experiment_name, run_id,
        name, status, start_time_ms, end_time_ms, params, tags,
        parent_run_id, source_commit, artifact_dir, artifact_uri,
        artifact_remote, datasets, metrics (lazy callable).
    """
    if client is None:
        MlflowClient = _import_mlflow_client()
        client = MlflowClient(tracking_uri)

    experiment_filter = set(experiments) if experiments else None

    # Collect filtered experiment IDs and a name-lookup map in one pass, then
    # fetch all runs in a single search_runs call sequence (avoids N separate
    # paged requests for N experiments).
    exp_name_by_id: Dict[str, str] = {}
    for exp in _iter_pages_experiments(client, include_deleted):
        if experiment_filter is not None and exp.name not in experiment_filter:
            continue
        exp_name_by_id[exp.experiment_id] = exp.name

    if not exp_name_by_id:
        return

    for run in _iter_pages_runs(client, list(exp_name_by_id), include_deleted):
        yield _build_run_dict(run, exp_name_by_id[run.info.experiment_id], client)


def download_artifacts(client, run_id: str, dest: str) -> str:
    """Download all artifacts for *run_id* into *dest* directory.

    Parameters
    ----------
    client:
        An ``MlflowClient`` instance.
    run_id:
        The MLflow run ID whose artifacts to download.
    dest:
        Local directory path where artifacts will be written.

    Returns
    -------
    str
        Path to the downloaded artifact root.
    """
    os.makedirs(dest, exist_ok=True)
    return client.download_artifacts(run_id, "", dest)
