"""vmn-exp — experiment tracking SDK.

Self-contained on purpose: this package depends only on vmn_exp.core,
vmn_exp.storage, vmn_exp.registry and vmn_exp._base — never on version_stamp,
vmn_exp.snapshot, vmn_exp.ui or vmn_exp.cli (vmn_exp.gitmode only lazily) —
so it ships as its own distribution (packages/vmn-exp/tests/test_packaging_split.py).
"""
import importlib
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
from vmn_exp.core.writer import RunExistsError  # noqa: E402
from vmn_exp.sdk.create import create_run, create_runs  # noqa: E402
from vmn_exp.sdk.ranks import NoOpRun  # noqa: E402
from vmn_exp.sdk.run import Run, install_signal_handlers, start_run  # noqa: E402  (needs the helper above)
from vmn_exp.sdk.sweep import sweep_params  # noqa: E402
from vmn_exp.sdk.fork_safety import (  # noqa: E402
    background_paused,
    pause_background,
    resume_background,
)

# Registry and reader names load on first use: their modules pull in the
# registry store and the index, which a metrics-only job never needs (plan 41
# D2, D10). vmn_exp.sdk.reader stays the readers' canonical module.
_READERS = (
    "get_lineage",
    "get_metric_history",
    "get_run",
    "get_run_state",
    "get_run_states",
    "list_runs",
    "param_importance",
    "runs_dataframe",
    "similar_runs",
)
_LAZY = {
    **dict.fromkeys(_READERS, "vmn_exp.sdk.reader"),
    "resolve_storage": "vmn_exp.sdk.store_resolve",
    "download_model": "vmn_exp.sdk.models",
    "get_model_version": "vmn_exp.sdk.models",
    "list_models": "vmn_exp.sdk.models",
    "register_model": "vmn_exp.sdk.models",
    "remove_alias": "vmn_exp.sdk.models",
    "set_alias": "vmn_exp.sdk.models",
    "get_dataset_version": "vmn_exp.sdk.datasets",
    "register_dataset": "vmn_exp.sdk.datasets",
    "use_dataset": "vmn_exp.sdk.usage",
    "use_model": "vmn_exp.sdk.usage",
}


def __getattr__(name):
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(_LAZY[name]), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY))


__all__ = [
    "NoOpRun",
    "Run",
    "RunExistsError",
    "autolog",
    "autolog_disable",
    "background_paused",
    "create_run",
    "create_runs",
    "current_run",
    "download_model",
    "get_dataset_version",
    "get_model_version",
    "install_signal_handlers",
    "list_models",
    "pause_background",
    "register_dataset",
    "register_model",
    "remove_alias",
    "resolve_storage",
    "resume_background",
    "set_alias",
    "start_run",
    "sweep_params",
    "use_dataset",
    "use_model",
    *_READERS,
]
