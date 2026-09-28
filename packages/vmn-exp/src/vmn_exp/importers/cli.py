"""CLI handler for ``vmn-exp import-mlflow`` (B4).

Reads runs from an MLflow source (FileStore ``mlruns/`` dir or tracking server)
and writes them into vmn-exp storage.

Boundary: this module is EXPERIMENTS side.  May import from:
  - stdlib
  - vmn_exp.snapshot (experiments side)
  - vmn_exp.importers.*
  - version_stamp.api (facade for any stamping helpers — none needed here)
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterator, List, Optional, Tuple

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------


def _get_storage(args):
    """Resolve experiment storage from args / environment variables."""
    from vmn_exp.core.storage_resolve import resolve_experiment_storage

    return resolve_experiment_storage(
        dir=getattr(args, "experiment_dir", None),
        bucket=getattr(args, "bucket", None),
        prefix=getattr(args, "prefix", None),
        endpoint_url=getattr(args, "endpoint_url", None),
    )


# ---------------------------------------------------------------------------
# Run source iterator
# ---------------------------------------------------------------------------


def _stream_runs(args) -> Iterator[Dict[str, Any]]:
    """Yield neutral run dicts from the source specified in *args*."""
    mlruns_path: Optional[str] = getattr(args, "mlruns", None)
    tracking_uri: Optional[str] = getattr(args, "tracking_uri", None)
    experiments: List[str] = list(getattr(args, "experiment", None) or [])
    include_deleted: bool = bool(getattr(args, "include_deleted", False))

    if mlruns_path:
        from vmn_exp.importers.mlflow_filestore import iter_runs
        yield from iter_runs(
            mlruns_path,
            experiments=experiments or None,
            include_deleted=include_deleted,
        )
    else:
        from vmn_exp.importers.mlflow_client import iter_runs as client_iter_runs
        yield from client_iter_runs(
            tracking_uri,
            experiments=experiments or None,
            include_deleted=include_deleted,
        )


# ---------------------------------------------------------------------------
# Per-run import (used in thread pool)
# ---------------------------------------------------------------------------


def _import_one(
    storage,
    app_name: str,
    run: Dict[str, Any],
    skip_artifacts: bool,
) -> Tuple[str, str]:
    """Import a single run; return (outcome, run_id).

    *outcome* is one of ``"created"``, ``"skipped"``, ``"resumed"``, or
    ``"failed"`` (the last only when an exception is raised).
    """
    from vmn_exp.importers.import_records import import_run

    run_id = run.get("run_id", "unknown")
    try:
        outcome = import_run(storage, app_name, run, skip_artifacts=skip_artifacts)
        return outcome, run_id
    except Exception:
        _LOG.exception("import-mlflow: failed to import run %s", run_id)
        return "failed", run_id


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------


def import_mlflow_run_without_repo(args) -> Optional[int]:
    """Handler for ``vmn-exp import-mlflow``.

    Called via ``run_without_repo`` so the repo lock is never acquired.
    Returns an integer exit code (0 = success, 1 = any run failed or bad args).
    """
    mlruns_path: Optional[str] = getattr(args, "mlruns", None)
    tracking_uri: Optional[str] = getattr(args, "tracking_uri", None)
    app_name: str = getattr(args, "name", "") or ""
    skip_artifacts: bool = bool(getattr(args, "skip_artifacts", False))
    dry_run: bool = bool(getattr(args, "dry_run", False))
    workers: int = int(getattr(args, "workers", 8) or 8)

    # Validate exactly one source.  Argparse's mutually_exclusive_group prevents
    # both from being set in normal CLI use; the "both" branch handles programmatic
    # callers (tests, SDK) that bypass argparse.
    if not mlruns_path and not tracking_uri:
        print("error: one of --mlruns or --tracking-uri is required")
        return 1
    if mlruns_path and tracking_uri:
        print(
            "error: --mlruns and --tracking-uri are mutually exclusive; "
            "specify exactly one source"
        )
        return 1

    if not app_name:
        print("error: app name is required")
        return 1

    # Collect runs eagerly; needed for dry-run count and pool submission.
    # Metric data inside each run is a lazy callable, so memory cost is small.
    try:
        runs = list(_stream_runs(args))
    except Exception:
        _LOG.exception("import-mlflow: failed to read source")
        return 1

    if dry_run:
        _print_dry_run(runs)
        return 0

    storage = _get_storage(args)
    n_created = n_skipped = n_resumed = n_failed = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Store only run_id in the dict (not the full run) to release run
        # objects as futures complete.
        futures: Dict[Any, str] = {
            pool.submit(_import_one, storage, app_name, run, skip_artifacts): run.get(
                "run_id", "unknown"
            )
            for run in runs
        }
        for future in as_completed(futures):
            outcome, run_id = future.result()
            del futures[future]
            if outcome == "created":
                n_created += 1
            elif outcome == "skipped":
                n_skipped += 1
            elif outcome == "resumed":
                n_resumed += 1
            else:
                n_failed += 1
                # _import_one already logged the exception; count only here.

    print(
        f"imported {n_created}, skipped {n_skipped} (already present), "
        f"resumed {n_resumed}, failed {n_failed}"
    )

    return 1 if n_failed > 0 else 0


def _print_dry_run(runs: List[Dict[str, Any]]) -> None:
    """Print what would be imported without writing anything."""
    from vmn_exp.importers.import_records import run_verstr

    print(f"dry-run: would import {len(runs)} run(s)")
    for run in runs:
        rid = run.get("run_id", "?")
        verstr = run_verstr(rid)
        name = run.get("name") or ""
        exp = run.get("experiment_name") or run.get("experiment_id") or ""
        suffix = f" ({name})" if name else ""
        print(f"  {verstr}{suffix}  [experiment: {exp}]")
