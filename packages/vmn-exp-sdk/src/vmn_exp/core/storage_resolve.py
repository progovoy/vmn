"""Unified experiment storage resolution helper.

Single source of truth for the resolution order shared by:
- ``vmn-exp``  (vmn_exp.cli.experiment._get_experiment_storage)
- ``vmn-exp model`` (vmn_exp.registry.cli._get_storage)
- ``vmn-exp import-mlflow`` (vmn_exp.importers.cli._get_storage)
- SDK (vmn_exp.sdk.models._resolve_storage)

The local root (highest wins):
1. Explicit ``dir`` argument (the --dir flag)
2. ``VMN_EXPERIMENT_DIR`` environment variable
3. ``repo_root`` argument, or auto-detected git/.vmn root from cwd: its
   repo-local store ``<repo>/.vmn/store``

It fronts the remote store, if any: ``store`` (--store) >
``VMN_EXPERIMENT_STORE`` > conf ``experiment.storage.uri``, else the
``bucket``/``prefix``/``endpoint_url`` shorthand for an ``s3://`` URI. Without
a local root the store is used directly; a ``file://`` store is the root.
"""
from __future__ import annotations

import os

from vmn_exp.storage.areas import DEFAULT_ROOT, RUNS, local_store_root


def resolve_experiment_storage(
    *,
    dir: "str | None" = None,
    store: "str | None" = None,
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
    store:
        Storage URI (``s3://``, ``gs://``, ``az://``, ``file://``, plugins).
    bucket, prefix, endpoint_url:
        Shorthand for ``s3://bucket/prefix?endpoint_url=...``; ``store`` wins.
    repo_root:
        Caller-supplied repo root (skips the auto-detect step).  Pass
        ``False`` to suppress auto-detect entirely (useful in tests or when
        the caller is certain there is no git checkout).
    """
    from vmn_exp.core.writer import merge_env_into_params

    root = dir or os.environ.get("VMN_EXPERIMENT_DIR")
    if not root and repo_root is not False:
        root = _repo_store(repo_root if repo_root is not None else _try_repo_root())

    params = {
        "store": store,
        "bucket": bucket,
        "prefix": prefix,
        "endpoint_url": endpoint_url,
    }
    merge_env_into_params(params)
    return _open(root, params)


def store_uri(params, default_prefix=DEFAULT_ROOT):
    """The store URI *params* name: ``store``, else the bucket shorthand
    (its prefix is the store root)."""
    from vmn_exp.storage.uri import s3_uri

    if params.get("store"):
        return params["store"]
    if params.get("bucket"):
        return s3_uri(
            params["bucket"],
            params.get("prefix") or default_prefix,
            params.get("endpoint_url"),
        )
    return None


_REMOTE_PARAMS = ("store", "bucket", "prefix", "endpoint_url")


def drop_remote_if_offline(params, root):
    """*params* without their remote store under ``VMN_EXP_OFFLINE``.

    conf.yml is committed and shared with compute nodes that may have no
    network, so offline mode must win over it. Offline, runs record to the
    local root alone (``vmn exp push`` uploads them later): ValueError when
    there is none. Never a silent fallback when a remote is unreachable.
    """
    from vmn_exp.core.writer import OFFLINE_ENV, offline_mode

    if not offline_mode():
        return params
    if not root:
        raise ValueError(
            f"{OFFLINE_ENV} records to a local experiment dir: set "
            "VMN_EXPERIMENT_DIR (or --experiment-dir/--dir, or run in a checkout)"
        )
    return {k: v for k, v in params.items() if k not in _REMOTE_PARAMS}


def _open(root, params, writer=True):
    from vmn_exp.storage.open import open_storage

    params = drop_remote_if_offline(params, root)
    return open_storage(store_uri(params), root, area=RUNS, buffer_logs=True,
                        writer=writer)


def _try_repo_root() -> "str | None":
    """Return the .vmn / .git root for the current working directory, or None."""
    try:
        from vmn_exp._base import resolve_root_path
        return resolve_root_path()
    except (RuntimeError, OSError):
        # RuntimeError: no .git/.vmn found walking up to filesystem root.
        # OSError: e.g. permission error reading a parent directory.
        return None


def _repo_store(repo_root):
    return local_store_root(repo_root) if repo_root else None


def experiment_dir(vcs, params):
    """The local store root: ``--dir``, ``$VMN_EXPERIMENT_DIR``, else the
    repo-local store."""
    return (params.get("experiment_dir") or os.environ.get("VMN_EXPERIMENT_DIR")
            or _repo_store(vcs.vmn_root_path if vcs else None))


def _get_experiment_storage(vcs, params, writer=True):
    return _open(experiment_dir(vcs, params), params, writer)


def add_storage_flags(parser):
    """The store flags every storage-opening command takes. ``--prefix`` has
    no default: :func:`store_uri` supplies it, so an explicit one always wins."""
    parser.add_argument("--store", default=None,
                        help="Storage URI: s3://bucket/prefix, gs://..., az://..., "
                             "file:///dir (or VMN_EXPERIMENT_STORE)")
    parser.add_argument("--bucket", default=None,
                        help="S3 bucket name (shorthand for --store s3://BUCKET/PREFIX)")
    parser.add_argument("--prefix", default=None,
                        help="S3 key prefix: the store root (default: vmn)")
    parser.add_argument("--endpoint-url", dest="endpoint_url", default=None,
                        help="Custom S3 endpoint URL")
