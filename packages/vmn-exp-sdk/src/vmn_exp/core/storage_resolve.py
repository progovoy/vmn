"""Unified experiment storage resolution helper.

Single source of truth for the resolution order shared by:
- ``vmn-exp``  (vmn_exp.cli.experiment._get_experiment_storage)
- ``vmn-exp model`` (vmn_exp.cli.model_cmd._get_storage)
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

from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.storage.areas import DEFAULT_ROOT, RUNS, local_store_root

# Storage params an app's conf.yml may supply (param -> conf key).
_STORAGE_CONF_KEYS = {
    "store": "uri",
    "bucket": "bucket",
    "prefix": "prefix",
    "endpoint_url": "endpoint_url",
    "experiment_dir": "experiment_dir",
    "writer_id": "writer_id",
}

# Storage params a pod can set without a conf.yml (see merge_env_into_params).
STORAGE_ENV = {
    "store": "VMN_EXPERIMENT_STORE",
    "bucket": "VMN_EXPERIMENT_BUCKET",
    "prefix": "VMN_EXPERIMENT_PREFIX",
    "endpoint_url": "VMN_EXPERIMENT_ENDPOINT_URL",
}


def merge_env_into_params(params, env):
    """Fill unset storage params from *env*'s ``VMN_EXPERIMENT_*`` (flags override env).

    A pod has no conf.yml and often no checkout; the environment is how it is
    pointed at a bucket.
    """
    for key, var in STORAGE_ENV.items():
        if not params.get(key) and env.get(var):
            params[key] = env[var]


def merge_conf_into_params(vcs, params, env):
    """Fill unset storage params: CLI flags, then *env*'s ``VMN_EXPERIMENT_*``, then conf.yml."""
    merge_env_into_params(params, env)
    exp_conf = experiment_conf(vcs)
    storage_conf = exp_conf.get("storage", {}) or {}
    for key, conf_key in _STORAGE_CONF_KEYS.items():
        if not params.get(key):
            conf_val = storage_conf.get(conf_key)
            if conf_val:
                params[key] = conf_val


def resolve_experiment_storage(
    *,
    dir: "str | None" = None,
    store: "str | None" = None,
    bucket: "str | None" = None,
    prefix: "str | None" = None,
    endpoint_url: "str | None" = None,
    repo_root: "str | None" = None,
    clock,
    env,
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
    clock:
        What a direct-to-bucket store's log buffer times its flushes on.
    env:
        The environment ``VMN_EXPERIMENT_*`` and ``VMN_EXP_OFFLINE`` are read from.
    """
    root = dir or env.get("VMN_EXPERIMENT_DIR")
    if not root and repo_root is not False:
        root = _repo_store(repo_root if repo_root is not None else try_repo_root())

    params = {
        "store": store,
        "bucket": bucket,
        "prefix": prefix,
        "endpoint_url": endpoint_url,
    }
    merge_env_into_params(params, env)
    return _open(root, params, clock=clock, env=env)


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


def drop_remote_if_offline(params, root, env):
    """*params* without their remote store under *env*'s ``VMN_EXP_OFFLINE``.

    conf.yml is committed and shared with compute nodes that may have no
    network, so offline mode must win over it. Offline, runs record to the
    local root alone (``vmn exp push`` uploads them later): ValueError when
    there is none. Never a silent fallback when a remote is unreachable.
    """
    from vmn_exp.core.writer import OFFLINE_ENV, offline_mode

    if not offline_mode(env):
        return params
    if not root:
        raise ValueError(
            f"{OFFLINE_ENV} records to a local experiment dir: set "
            "VMN_EXPERIMENT_DIR (or --experiment-dir/--dir, or run in a checkout)"
        )
    return {k: v for k, v in params.items() if k not in _REMOTE_PARAMS}


def _open(root, params, writer=True, *, clock, env):
    from vmn_exp.storage.open import open_storage

    params = drop_remote_if_offline(params, root, env)
    return open_storage(store_uri(params), root, area=RUNS, buffer_logs=True,
                        writer=writer, lent_options=_lent_options(params), clock=clock)


def _lent_options(params):
    """A configured ``endpoint_url`` for absolute ``s3://`` downloads when
    no remote store carries it."""
    endpoint_url = params.get("endpoint_url")
    return {"s3": {"endpoint_url": endpoint_url}} if endpoint_url else None


def try_repo_root() -> "str | None":
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


def experiment_dir(vcs, params, env):
    """The local store root: ``--dir``, *env*'s ``$VMN_EXPERIMENT_DIR``, else
    the repo-local store."""
    return (params.get("experiment_dir") or env.get("VMN_EXPERIMENT_DIR")
            or _repo_store(vcs.vmn_root_path if vcs else None))


def _get_experiment_storage(vcs, params, writer=True, *, clock, env):
    return _open(experiment_dir(vcs, params, env), params, writer, clock=clock, env=env)

