"""vmn-exp — experiment tracking SDK.

Self-contained on purpose: this package depends on vmn_exp.core, vmn_exp.storage,
vmn_exp.snapshot, and version_stamp.api — never on vmn_exp.ui or vmn_exp.cli —
so the SDK can be lifted out as its own distribution later.
"""
import os

APP_NAME_ENV = "VMN_APP_NAME"


def _resolve_app_name(app_name, candidates):
    """The app to record against, or to read from, when the caller named none.

    One rule for the write side and the read side: an explicit name wins, then
    ``VMN_APP_NAME`` (which ``vmn-exp run`` exports to its child, so a script it
    launched needs no argument), then the checkout's sole app. *candidates* lists
    what the caller counts as eligible — stamped apps for the writer, apps with
    experiments for the reader.
    """
    if app_name:
        return app_name

    from_env = os.environ.get(APP_NAME_ENV)
    if from_env:
        return from_env

    apps = candidates()
    if len(apps) == 1:
        return apps[0]

    raise ValueError(
        f"Cannot infer the vmn app name from this repository "
        f"(candidates: {', '.join(apps) or 'none'}). "
        f"Pass app_name= explicitly or set {APP_NAME_ENV}."
    )


from vmn_exp.sdk.autolog import autolog, autolog_disable  # noqa: E402
from vmn_exp.sdk.context import current_run  # noqa: E402
from vmn_exp.sdk.models import (  # noqa: E402
    download_model,
    get_model_version,
    list_models,
    register_model,
    remove_alias,
    set_alias,
)
from vmn_exp.sdk.ranks import NoOpRun  # noqa: E402
from vmn_exp.sdk.run import Run, start_run  # noqa: E402  (needs the helper above)

__all__ = [
    "NoOpRun",
    "Run",
    "autolog",
    "autolog_disable",
    "current_run",
    "download_model",
    "get_model_version",
    "list_models",
    "register_model",
    "remove_alias",
    "set_alias",
    "start_run",
]
