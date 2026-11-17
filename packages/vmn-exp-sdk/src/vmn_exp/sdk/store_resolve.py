"""``vmn_exp.sdk.resolve_storage``: the public way to build a ``storage=``.

Its own function, not the core resolver re-exported: the keyword-only
parameters below are the public contract, and the core resolver stays free to
change behind it (plan 41 D10).
"""
from vmn_exp.core.app_conf import read_app_conf
from vmn_exp.core.real_io import real_io
from vmn_exp.core.storage_resolve import (
    _get_experiment_storage, resolve_experiment_storage, try_repo_root)
from vmn_exp.core.writer import merge_conf_into_params, merge_env_into_params
from vmn_exp.sdk import APP_NAME_ENV


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


def checkout_storage(app_name=None, repo_root=None):
    """The storage a reader of *app_name* (else ``VMN_APP_NAME``) reads: where
    :func:`start_run` records it. Inside the checkout *repo_root* (auto-detected
    when None; ``False``: none) the app's conf.yml ``store`` (else the legacy
    ``experiment.storage``) names the store after the environment; with no app
    named it is the checkout's sole stamped app, as :func:`start_run` infers it.
    Outside a checkout, or with no app to name, the environment alone names the
    store, as :func:`resolve_storage`.
    An SDK entry point like it."""
    io = real_io()
    root = try_repo_root() if repo_root is None else repo_root
    return storage_of_checkout(app_name, root, io.env, io.clock, stamped_apps=_stamped_apps)


def storage_of_checkout(app_name, root, env, clock, stamped_apps):
    """:func:`checkout_storage` over the given IO."""
    app = app_name or env.get(APP_NAME_ENV) or (root and _sole(stamped_apps()))
    conf = read_app_conf(app, root) if root and app else None
    return resolve_experiment_storage(repo_root=root or False, conf=conf,
                                      clock=clock, env=env)


def _sole(apps):
    return apps[0] if len(apps) == 1 else None


def _stamped_apps():
    """The checkout's stamped apps, as :func:`start_run` infers its app from;
    none without git mode (an SDK-only install records with no checkout)."""
    try:
        from vmn_exp.gitmode import checkout
    except ImportError:
        return []
    return checkout.stamped_apps()


def configured_storage(vcs, params, writer=True):
    """The storage *vcs*'s checkout (or none) and *params* name, for the SDK
    functions that resolve one themselves: like :func:`resolve_storage`, an
    entry point that builds the real IO the resolver takes."""
    io = real_io()
    return _get_experiment_storage(vcs, params, writer, clock=io.clock, env=io.env)


def env_storage():
    """The storage ``VMN_EXPERIMENT_DIR`` and ``VMN_STORE*`` (else ``VMN_EXPERIMENT_*``) name, for a
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
