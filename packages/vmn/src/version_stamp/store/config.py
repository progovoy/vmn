"""Which store a command uses: flags, environment and conf.yml (plan 37).

Pure: the caller passes the CLI params, the environment as a mapping and the
app's conf mapping (the dict under ``conf:``). Each store param is filled from
the first source that sets it (an empty value is unset):

1. the flags (``store``, ``bucket``, ``prefix``, ``endpoint_url``)
2. ``VMN_STORE*``, then their ``VMN_EXPERIMENT_*`` twins
3. conf ``store``, then the legacy conf ``experiment.storage``

then a ``store`` URI wins over the ``bucket``/``prefix``/``endpoint_url``
shorthand for an ``s3://`` URI (prefix default ``vmn``). ``local`` and a truthy
``VMN_EXP_OFFLINE`` mean the repo-local store. The same order as the SDK's
``vmn_exp.core.writer.merge_conf_into_params``, so installing vmn-exp never
moves snapshots.
"""
from version_stamp.store.areas import DEFAULT_ROOT
from version_stamp.store.uri import s3_uri

OFFLINE_ENV = "VMN_EXP_OFFLINE"
_TRUE_VALUES = ("1", "true", "yes", "on")

# Store param -> the env names that set it, first wins.
STORE_ENV = {
    "store": ("VMN_STORE", "VMN_EXPERIMENT_STORE"),
    "bucket": ("VMN_STORE_BUCKET", "VMN_EXPERIMENT_BUCKET"),
    "prefix": ("VMN_STORE_PREFIX", "VMN_EXPERIMENT_PREFIX"),
    "endpoint_url": ("VMN_STORE_ENDPOINT_URL", "VMN_EXPERIMENT_ENDPOINT_URL"),
}

# Store param -> its key in a conf ``store`` / ``experiment.storage`` section.
_CONF_KEYS = {
    "store": "uri",
    "bucket": "bucket",
    "prefix": "prefix",
    "endpoint_url": "endpoint_url",
}


def is_true(value):
    """Whether an env value (maybe None) says yes: 1/true/yes/on."""
    return (value or "").strip().lower() in _TRUE_VALUES


def offline_mode(env):
    return is_true(env.get(OFFLINE_ENV))


def conf_store_sections(conf):
    """The conf sections that may name a store, in precedence order."""
    experiment = conf.get("experiment") or {}
    return [conf.get("store") or {}, experiment.get("storage") or {}]


def _first(values):
    return next((v for v in values if v), None)


def store_params(params, env, conf):
    """A copy of *params* with each store param filled from its sources."""
    sections = conf_store_sections(conf)
    merged = dict(params)
    for key, names in STORE_ENV.items():
        merged[key] = _first(
            [params.get(key)]
            + [env.get(name) for name in names]
            + [section.get(_CONF_KEYS[key]) for section in sections]
        )
    return merged


def drop_remote_if_offline(params, env):
    """*params* without their remote store under ``VMN_EXP_OFFLINE``: conf.yml
    is committed and shared with machines that may have no network."""
    if not offline_mode(env):
        return params
    return {k: v for k, v in params.items() if k not in STORE_ENV}


def store_uri(params, default_prefix=DEFAULT_ROOT):
    """The store URI *params* name: ``store``, else the bucket shorthand."""
    if params.get("store"):
        return params["store"]
    if params.get("bucket"):
        return s3_uri(
            params["bucket"],
            params.get("prefix") or default_prefix,
            params.get("endpoint_url"),
        )
    return None


def _resolved_params(params, env, conf):
    if params.get("local"):
        return {}
    return drop_remote_if_offline(store_params(params, env, conf), env)


def resolve_store_uri(params, env, conf):
    """The store URI to use, or None for the repo-local store."""
    return store_uri(_resolved_params(params, env, conf))


def resolve_store(params, env, conf):
    """``(uri, options)``: :func:`resolve_store_uri` and the backend options a
    configured ``endpoint_url`` gives absolute ``s3://`` reads (the SDK's
    lent options), None without one."""
    resolved = _resolved_params(params, env, conf)
    endpoint_url = resolved.get("endpoint_url")
    options = {"s3": {"endpoint_url": endpoint_url}} if endpoint_url else None
    return store_uri(resolved), options
