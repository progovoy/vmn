"""``vmn_exp.sdk.resolve_storage``: the public way to build a ``storage=``.

Its own function, not the core resolver re-exported: the keyword-only
parameters below are the public contract, and the core resolver stays free to
change behind it (plan 41 D10).
"""
from vmn_exp.core.real_io import real_io
from vmn_exp.core.storage_resolve import _get_experiment_storage, resolve_experiment_storage
from vmn_exp.core.writer import merge_conf_into_params, merge_env_into_params


def resolve_storage(*, dir: str | None = None, store: str | None = None,
                    bucket: str | None = None, prefix: str | None = None,
                    endpoint_url: str | None = None, repo_root=None):
    """The experiment storage for *dir* or *store* (``s3://``, ``gs://``,
    ``az://``, ``file://``, plugins); *bucket*/*prefix*/*endpoint_url* are the
    S3 shorthand. ``repo_root=False`` skips finding a checkout."""
    io = real_io()
    return resolve_experiment_storage(dir=dir, store=store, bucket=bucket, prefix=prefix,
                                      endpoint_url=endpoint_url, repo_root=repo_root,
                                      clock=io.clock, env=io.env)


def configured_storage(vcs, params, writer=True):
    """The storage *vcs*'s checkout (or none) and *params* name, for the SDK
    functions that resolve one themselves: like :func:`resolve_storage`, an
    entry point that builds the real IO the resolver takes."""
    io = real_io()
    return _get_experiment_storage(vcs, params, writer, clock=io.clock, env=io.env)


def env_storage():
    """The storage ``VMN_EXPERIMENT_DIR`` and ``VMN_EXPERIMENT_*`` name, for a
    run without a checkout: an entry point like :func:`configured_storage`."""
    io = real_io()
    params = {}
    merge_env_into_params(params, io.env)
    return _get_experiment_storage(None, params, clock=io.clock, env=io.env)


def conf_storage(vcs):
    """The storage *vcs*'s conf.yml (and ``VMN_EXPERIMENT_*``) names, for the
    SDK's git mode, which opens one when ``start_run`` was given none: an
    entry point like :func:`configured_storage`."""
    io = real_io()
    params = {}
    merge_conf_into_params(vcs, params, io.env)
    return _get_experiment_storage(vcs, params, clock=io.clock, env=io.env)
