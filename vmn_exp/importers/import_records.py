"""Write a vmn experiment record from a neutral MLflow run dict (B3).

Public API::

    run_verstr(run_id) -> str
        Deterministic verstr ``0.0.0-mlflow.<run_id[:12]>`` for a run.

    import_run(storage, app_name, run, *, skip_artifacts=False)
        -> "created" | "skipped" | "resumed"

Re-import policy:
- "skipped": metadata already present with the same ``imported_from.run_id``
  AND the log already has entries from the "mlflow-import" writer.
- "resumed": metadata is present and matches but the log is empty/incomplete
  (a partial import from a previous crash). The missing log entries are
  written; the result is "resumed".
- "created": the verstr was free; full import is written.

Tags mapping: ``mlflow.*`` system keys are skipped (runName/parentRunId/
source.git.commit are already extracted into structured metadata fields).
All other tags become vmn tags.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from version_stamp.core.experiment_inputs import create_input_entry
from version_stamp.core.experiment_writer import (
    claim_record,
    create_tags_entry,
    flush_log,
    save_run_state,
)
from version_stamp.core.utils import now_iso

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMPORT_WRITER = "mlflow-import"


# ---------------------------------------------------------------------------
# Verstr helpers
# ---------------------------------------------------------------------------


def run_verstr(run_id: str) -> str:
    """Deterministic vmn verstr for an MLflow run: ``0.0.0-mlflow.<id12>``."""
    return f"0.0.0-mlflow.{run_id[:12]}"


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _ms_to_iso_us(ts_ms: int) -> str:
    """Convert a millisecond epoch to a microsecond-precision ISO-8601 UTC string."""
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


_OLD_HEARTBEAT = "1970-01-01T00:00:00.000000Z"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_metadata(run: Dict[str, Any], verstr: str) -> Dict[str, Any]:
    """Build the metadata.yml dict for an imported run."""
    meta: Dict[str, Any] = {
        "verstr": verstr,
        "code_verstr": verstr,
        "imported_from": {
            "tool": "mlflow",
            "run_id": run["run_id"],
            "experiment_id": run["experiment_id"],
            "experiment_name": run["experiment_name"],
            "source_commit": run.get("source_commit"),
            "artifact_uri": run["artifact_uri"],
        },
    }
    if run.get("name"):
        meta["name"] = run["name"]
    parent_run_id = run.get("parent_run_id")
    if parent_run_id:
        meta["parent"] = run_verstr(parent_run_id)
    if run.get("start_time_ms"):
        meta["timestamp"] = _ms_to_iso_us(run["start_time_ms"])
    return meta


def _build_log_entries(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build all log entries for a run in one pass; returned in write order."""
    entries: List[Dict[str, Any]] = []

    # 1. create entry (with params, timestamp from start_time)
    create_ts = (
        _ms_to_iso_us(run["start_time_ms"]) if run.get("start_time_ms") else now_iso()
    )
    create_entry: Dict[str, Any] = {"timestamp": create_ts, "type": "create"}
    if run.get("params"):
        create_entry["params"] = dict(run["params"])
    entries.append(create_entry)

    # 2. metrics grouped by (timestamp_ms, step)
    grouped: Dict[tuple, Dict[str, Any]] = {}
    for key, value, ts_ms, step in run["metrics"]():
        group_key = (ts_ms, step)
        if group_key not in grouped:
            grouped[group_key] = {"ts_ms": ts_ms, "step": step, "values": {}}
        grouped[group_key]["values"][key] = value

    for (ts_ms, step), group in sorted(grouped.items()):
        entries.append({
            "timestamp": _ms_to_iso_us(ts_ms),
            "type": "metrics",
            "values": group["values"],
            "step": step,
        })

    # 3. tags (skip all mlflow.* — mapped ones go into metadata)
    user_tags = {
        k: v
        for k, v in (run.get("tags") or {}).items()
        if not k.startswith("mlflow.")
    }
    if user_tags:
        entries.append(create_tags_entry(user_tags))

    # 4. input entries from datasets (one shared timestamp for the batch)
    input_ts = now_iso()
    for ds in run.get("datasets") or []:
        uri = ds.get("source") or ds.get("name") or ""
        if not uri:
            continue
        entries.append(create_input_entry(
            uri=uri,
            name=ds.get("name"),
            digest=ds.get("digest") or None,
            kind=ds.get("source_type") or None,
            ts=input_ts,
        ))

    return entries


def _build_run_state(run: Dict[str, Any]) -> Dict[str, Any]:
    """Derive a run_state.yml dict from the MLflow status."""
    status = (run.get("status") or "").upper()
    state: Dict[str, Any] = {"pid": 0, "host": "mlflow-import"}
    if status in ("FINISHED", "FAILED", "KILLED"):
        state["exit_code"] = 0 if status == "FINISHED" else 1
        if run.get("start_time_ms"):
            state["heartbeat"] = _ms_to_iso_us(run["start_time_ms"])
    else:  # RUNNING, SCHEDULED → stuck (no exit_code, stale heartbeat)
        state["heartbeat"] = _OLD_HEARTBEAT
        state["heartbeat_interval_sec"] = 30
    return state


def _copy_local_artifacts(
    storage, app_name: str, verstr: str, artifact_dir: Optional[str]
) -> None:
    """Walk *artifact_dir* and upload each file into the experiment record."""
    if not artifact_dir or not os.path.isdir(artifact_dir):
        return
    for dirpath, _, filenames in os.walk(artifact_dir):
        for fname in filenames:
            src = os.path.join(dirpath, fname)
            rel = os.path.relpath(src, artifact_dir)
            storage.save_artifact_file(app_name, verstr, src, name=rel)


def _has_import_log(storage, app_name: str, verstr: str) -> bool:
    """Return True when the mlflow-import writer has already written entries."""
    by_writer = getattr(storage, "load_logs_by_writer", None)
    if by_writer is not None:
        return bool(by_writer(app_name, verstr).get(IMPORT_WRITER))
    return bool(storage.log_sizes(app_name, verstr).get(IMPORT_WRITER))


def _write_all(
    storage, app_name: str, verstr: str, run: Dict[str, Any], skip_artifacts: bool
) -> None:
    """Write log entries + run_state + artifacts for a run."""
    entries = _build_log_entries(run)

    # Write directly to storage (not via append_entries_to_log) because
    # sanitize_entry is designed for live SDK writes and drops NaN; NaN is
    # valid MLflow data and must be preserved per the import spec.
    storage.append_log_entries(app_name, verstr, IMPORT_WRITER, entries)

    save_run_state(storage, app_name, verstr, _build_run_state(run))

    if not skip_artifacts and not run.get("artifact_remote"):
        _copy_local_artifacts(storage, app_name, verstr, run.get("artifact_dir"))

    flush_log(storage, app_name, verstr)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def import_run(
    storage,
    app_name: str,
    run: Dict[str, Any],
    *,
    skip_artifacts: bool = False,
) -> Literal["created", "skipped", "resumed"]:
    """Write a vmn experiment record from a neutral MLflow run dict.

    Parameters
    ----------
    storage:
        A vmn snapshot storage backend (local or S3).
    app_name:
        The vmn app name to import into.
    run:
        A neutral run dict as yielded by ``mlflow_filestore.iter_runs`` or
        ``mlflow_client.iter_runs``.
    skip_artifacts:
        When ``True``, local artifacts are not copied into storage (remote
        artifact URIs are never copied regardless).

    Returns
    -------
    "created":
        The run was freshly imported.
    "skipped":
        The run was already fully imported (same ``run_id``).
    "resumed":
        The run had been partially imported (metadata written but log empty)
        and the missing entries were now written.
    """
    verstr = run_verstr(run["run_id"])
    metadata = _build_metadata(run, verstr)

    # Attempt atomic claim
    if not claim_record(storage, app_name, verstr, metadata):
        # Record exists — check for same run and completeness
        existing = storage.load_metadata(app_name, verstr)
        existing_if = (existing or {}).get("imported_from", {})
        if existing_if.get("run_id") == run["run_id"]:
            if _has_import_log(storage, app_name, verstr):
                return "skipped"
            # Partial: claimed but log never written — resume
            _write_all(storage, app_name, verstr, run, skip_artifacts)
            return "resumed"
        # Different run mapped to same verstr prefix (collision); treat as skipped
        return "skipped"

    # Fresh claim succeeded — write everything
    _write_all(storage, app_name, verstr, run, skip_artifacts)
    return "created"
