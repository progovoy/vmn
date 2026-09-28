"""Unified experiment storage resolution helper.

Single source of truth for the resolution order shared by:
- ``vmn-exp``  (vmn_exp.cli.experiment._get_experiment_storage)
- ``vmn-exp model`` (vmn_exp.registry.cli._get_storage)
- ``vmn-exp import-mlflow`` (vmn_exp.importers.cli._get_storage)
- SDK (vmn_exp.sdk.models._resolve_storage)

Resolution order (highest wins):
1. Explicit ``dir`` argument (the --dir flag)
2. ``VMN_EXPERIMENT_DIR`` environment variable
3. ``repo_root`` argument, or auto-detected git/.vmn root from cwd
4. ``bucket`` / ``VMN_EXPERIMENT_BUCKET`` → pure S3 backend (no local root)
"""
from __future__ import annotations

import os


def resolve_experiment_storage(
    *,
    dir: "str | None" = None,
    bucket: "str | None" = None,
    prefix: "str | None" = None,
    endpoint_url: "str | None" = None,
    repo_root: "str | None" = None,
):
    """Return a configured snapshot storage for experiments.

    Parameters
    ----------
    dir:
        Explicit local root (highest priority).
    bucket:
        S3 bucket name.  When *dir* and env are both absent and the repo root
        cannot be found, a bucket forces the S3 backend.
    prefix:
        S3 key prefix (default ``"vmn-experiments"``).
    endpoint_url:
        Custom S3 endpoint URL.
    repo_root:
        Caller-supplied repo root (skips the auto-detect step).  Pass
        ``False`` to suppress auto-detect entirely (useful in tests or when
        the caller is certain there is no git checkout).
    """
    from vmn_exp.storage.cached import get_snapshot_storage

    # --- Step 1: determine the local root ---
    root = dir or os.environ.get("VMN_EXPERIMENT_DIR")

    if not root and repo_root is not False:
        root = repo_root if repo_root is not None else _try_repo_root()

    # --- Step 2: resolve bucket / prefix / endpoint from env fallbacks ---
    # merge_env_into_params fills unset keys from VMN_EXPERIMENT_{BUCKET,PREFIX,ENDPOINT_URL}
    from vmn_exp.core.writer import merge_env_into_params

    params = {
        "bucket": bucket,
        "prefix": prefix or "vmn-experiments",
        "endpoint_url": endpoint_url,
    }
    merge_env_into_params(params)
    eff_bucket = params["bucket"]
    eff_prefix = params["prefix"]
    eff_endpoint = params["endpoint_url"]

    return get_snapshot_storage(
        _pick_backend(root, eff_bucket),
        vmn_root_path=root,
        bucket=eff_bucket,
        prefix=eff_prefix,
        endpoint_url=eff_endpoint,
        subdir="experiments",
        buffer_logs=True,
    )


def _pick_backend(root, bucket):
    """Pure-S3 only when there is no local root AND a bucket is configured.
    (no root + no bucket → get_snapshot_storage raises a clear ValueError)"""
    return "s3" if (not root and bucket) else "local"


def _try_repo_root() -> "str | None":
    """Return the .vmn / .git root for the current working directory, or None."""
    try:
        from vmn_exp._base import resolve_root_path
        return resolve_root_path()
    except (RuntimeError, OSError):
        # RuntimeError: no .git/.vmn found walking up to filesystem root.
        # OSError: e.g. permission error reading a parent directory.
        return None


def _get_experiment_storage(vcs, params):
    experiment_dir = params.get("experiment_dir") or os.environ.get(
        "VMN_EXPERIMENT_DIR"
    )
    vmn_root = experiment_dir or (vcs.vmn_root_path if vcs else None)
    from vmn_exp.storage.cached import get_snapshot_storage

    return get_snapshot_storage(
        _pick_backend(vmn_root, params.get("bucket")),
        vmn_root_path=vmn_root,
        bucket=params.get("bucket"),
        prefix=params.get("prefix", "vmn-experiments"),
        endpoint_url=params.get("endpoint_url"),
        subdir="experiments",
        buffer_logs=True,
    )
