"""The store a ``vmn-exp`` command handed no vcs opens (``model``,
``import-mlflow``): inside a checkout, through the vcs core loads for the app
(:func:`~vmn_exp.cli.experiment.experiment_storage_params`, as the other
``vmn-exp`` commands), so conf.yml's ``store:`` (else the legacy
``experiment.storage``) names it after the flags and the environment; outside
one, the flags and the environment alone (no git)."""
from types import SimpleNamespace

from vmn_exp.core.storage_resolve import (
    _get_experiment_storage, resolve_experiment_storage, try_repo_root)

APP_NAME_ENV = "VMN_APP_NAME"


def command_storage(args, app_name, *, experiment_dir, clock, env, checkout):
    """The storage *args*' store flags and *experiment_dir* (the command's
    local-root flag) name, conf.yml filling the gaps inside *checkout*'s git
    checkout: the conf of *app_name*, else ``VMN_APP_NAME``, else the
    checkout's sole stamped app (with none to name, the flags and *env* alone)."""
    flags = SimpleNamespace(
        store=getattr(args, "store", None), bucket=getattr(args, "bucket", None),
        prefix=getattr(args, "prefix", None), endpoint_url=getattr(args, "endpoint_url", None),
        experiment_dir=experiment_dir)
    vcs = _checkout_vcs(app_name, env, checkout)
    if vcs is None:
        return resolve_experiment_storage(
            dir=flags.experiment_dir, store=flags.store, bucket=flags.bucket,
            prefix=flags.prefix, endpoint_url=flags.endpoint_url, clock=clock, env=env)
    from vmn_exp.cli.experiment import experiment_storage_params

    params = experiment_storage_params(vcs, flags, env)
    return _get_experiment_storage(vcs, params, clock=clock, env=env)


def _checkout_vcs(app_name, env, checkout):
    """The vcs of the app whose conf the command reads, or None outside a git
    checkout (a bare ``.vmn`` dir has no vcs) or with no app to name."""
    if checkout.git_root() is None:
        return None
    app = app_name or env.get(APP_NAME_ENV) or _sole(checkout.stamped_apps())
    return checkout.vcs(app) if app else None


def _sole(apps):
    return apps[0] if len(apps) == 1 else None


class CwdCheckout:
    """The real *checkout* of :func:`command_storage`: the git checkout above
    the working directory, read through core vmn. Entry points build it."""

    def git_root(self):
        """The checkout's root, or None outside one (a bare ``.vmn`` dir too)."""
        from version_stamp.api import VMN_BE_TYPE_GIT, get_client

        root = try_repo_root()
        if root is None or get_client(root, VMN_BE_TYPE_GIT)[1] is not None:
            return None
        return root

    def stamped_apps(self):
        from vmn_exp.gitmode.checkout import stamped_apps

        return stamped_apps()

    def vcs(self, app):
        from vmn_exp.gitmode.coldstart import build_vcs

        return build_vcs(app)
