"""Unified experiment storage resolution helper.

Single source of truth for the resolution order shared by:
- ``vmn-exp``  (vmn_exp.cli.experiment._get_experiment_storage)
- ``vmn-exp model`` (vmn_exp.cli.model_cmd._get_storage)
- ``vmn-exp import-mlflow`` (vmn_exp.importers.cli._get_storage)
- SDK (vmn_exp.sdk.models._resolve_storage)

The local root (highest wins):
1. Explicit ``dir`` argument (the --dir flag), else conf
   ``experiment.storage.experiment_dir``
2. ``VMN_EXPERIMENT_DIR`` environment variable
3. ``repo_root`` argument, or auto-detected git/.vmn root from cwd: its
   repo-local store ``<repo>/.vmn/store``

It fronts the remote store, if any, resolved by ``version_stamp.store.config``
(the table core's ``vmn snapshot`` uses): ``store`` (--store) > ``VMN_STORE`` >
``VMN_EXPERIMENT_STORE`` > conf ``store.uri`` > conf ``experiment.storage.uri``
(the conf of the checkout app a writer records to or a reader is handed;
outside a checkout the environment alone), else the
``bucket``/``prefix``/``endpoint_url`` shorthand for an ``s3://`` URI.
Without a local root the store is used directly; a ``file://`` store is the root.
"""
from __future__ import annotations

from version_stamp.store import config as store_config
from version_stamp.store.config import STORE_ENV

from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.storage.areas import DEFAULT_ROOT, RUNS, local_store_root

# vmn-exp's own params in conf ``experiment.storage`` (param -> conf key);
# the store params resolve through ``version_stamp.store.config``.
_STORAGE_CONF_KEYS = {
    "experiment_dir": "experiment_dir",
    "writer_id": "writer_id",
}

# Store param -> its legacy ``VMN_EXPERIMENT_*`` name. Each is read after its
# ``VMN_STORE*`` twin (``STORE_ENV`` holds both, in order).
STORAGE_ENV = {key: names[-1] for key, names in STORE_ENV.items()}


def _fill_store_params(params, env, conf):
    """Set each unset store param *params* gets from *env* and *conf*
    (``version_stamp.store.config.store_params``); unset ones stay absent."""
    resolved = store_config.store_params(params, env, conf)
    for key in STORE_ENV:
        if resolved[key] and not params.get(key):
            params[key] = resolved[key]


def merge_env_into_params(params, env):
    """Fill unset store params from *env*'s ``VMN_STORE*``, then
    ``VMN_EXPERIMENT_*`` (flags override env).

    A pod has no conf.yml and often no checkout; the environment is how it is
    pointed at a bucket.
    """
    _fill_store_params(params, env, {})


def _store_conf(vcs):
    """The conf sections of *vcs* that name a store, as core reads them."""
    return {"store": getattr(vcs, "store", None) or {},
            "experiment": experiment_conf(vcs)}


def merge_conf_into_params(vcs, params, env):
    """Fill unset storage params: CLI flags, then *env*, then *vcs*'s conf.yml
    (:func:`merge_app_conf_into_params`)."""
    merge_app_conf_into_params(_store_conf(vcs), params, env)


def merge_app_conf_into_params(conf, params, env):
    """Fill unset storage params: CLI flags, then *env*, then *conf* (an app's
    ``conf:`` mapping) — the store ones through ``version_stamp.store.config``
    (conf ``store`` before the legacy ``experiment.storage``),
    ``experiment_dir``/``writer_id`` from ``experiment.storage``."""
    _fill_store_params(params, env, conf)
    storage_conf = (conf.get("experiment") or {}).get("storage") or {}
    for key, conf_key in _STORAGE_CONF_KEYS.items():
        if not params.get(key):
            conf_val = storage_conf.get(conf_key)
            if conf_val:
                params[key] = conf_val


def reader_params(*, conf, env, dir=None, store=None, bucket=None, prefix=None,
                  endpoint_url=None):
    """The storage params :func:`resolve_experiment_storage` opens: the flags,
    then *env*, then *conf* — the order a writer in the same checkout uses.
    *conf* is ``{}`` outside a checkout, leaving the environment alone."""
    params = {"experiment_dir": dir, "store": store, "bucket": bucket, "prefix": prefix,
              "endpoint_url": endpoint_url}
    merge_app_conf_into_params(conf, params, env)
    return params


def resolve_experiment_storage(
    *,
    dir: "str | None" = None,
    store: "str | None" = None,
    bucket: "str | None" = None,
    prefix: "str | None" = None,
    endpoint_url: "str | None" = None,
    repo_root: "str | None" = None,
    conf=None,
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
    conf:
        The ``conf:`` mapping of the checkout app's conf.yml, read by the
        caller: its ``store`` (else the legacy ``experiment.storage``) names
        the store after the environment, as for a writer. None (no checkout,
        or no app to read) leaves the environment alone.
    clock:
        What a direct-to-bucket store's log buffer times its flushes on.
    env:
        The environment ``VMN_STORE*``, ``VMN_EXPERIMENT_*`` and ``VMN_EXP_OFFLINE`` are read from.
    """
    params = reader_params(conf=conf or {}, env=env, dir=dir, store=store, bucket=bucket,
                           prefix=prefix, endpoint_url=endpoint_url)
    root = params.pop("experiment_dir") or env.get("VMN_EXPERIMENT_DIR")
    params.pop("writer_id", None)
    if not root and repo_root is not False:
        root = _repo_store(repo_root if repo_root is not None else try_repo_root())
    return _open(root, params, clock=clock, env=env)


def store_uri(params, default_prefix=DEFAULT_ROOT):
    """The store URI *params* name: ``store``, else the bucket shorthand
    (its prefix is the store root)."""
    return store_config.store_uri(params, default_prefix)


def drop_remote_if_offline(params, root, env):
    """*params* without their remote store under *env*'s ``VMN_EXP_OFFLINE``.

    conf.yml is committed and shared with compute nodes that may have no
    network, so offline mode must win over it. Offline, runs record to the
    local root alone (``vmn exp push`` uploads them later): ValueError when
    there is none. Never a silent fallback when a remote is unreachable.
    """
    if store_config.offline_mode(env) and not root:
        raise ValueError(
            f"{store_config.OFFLINE_ENV} records to a local experiment dir: set "
            "VMN_EXPERIMENT_DIR (or --experiment-dir/--dir, or run in a checkout)"
        )
    return store_config.drop_remote_if_offline(params, env)


def _open(root, params, writer=True, *, clock, env):
    from vmn_exp.storage.open import open_storage

    params = drop_remote_if_offline(params, root, env)
    return open_storage(store_uri(params), root, area=RUNS, buffer_logs=True,
                        writer=writer, lent_options=store_config.store_options(params),
                        clock=clock, env=env)


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
