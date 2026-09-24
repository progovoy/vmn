"""vmn exp — experiment tracking: the CLI-facing SDK and its storage helpers.

Self-contained on purpose: this package depends on version_stamp.core and the
snapshot/storage helpers, never on version_stamp.ui, so the experiment feature
can be lifted out as its own distribution later.
"""
import os

APP_NAME_ENV = "VMN_APP_NAME"


def _resolve_app_name(app_name, candidates):
    """The app to record against, or to read from, when the caller named none.

    One rule for the write side and the read side: an explicit name wins, then
    ``VMN_APP_NAME`` (which ``vmn exp run`` exports to its child, so a script it
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


from version_stamp.exp.autolog import autolog, autolog_disable  # noqa: E402
from version_stamp.exp.context import current_run  # noqa: E402
from version_stamp.exp.ranks import NoOpRun  # noqa: E402
from version_stamp.exp.run import Run, start_run  # noqa: E402  (needs the helper above)

__all__ = [
    "NoOpRun",
    "Run",
    "autolog",
    "autolog_disable",
    "current_run",
    "start_run",
]
