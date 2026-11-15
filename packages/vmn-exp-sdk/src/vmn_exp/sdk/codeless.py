"""Runs that record no code: ``start_run(code=False)`` / ``VMN_EXP_CODE=none``.

Chosen only on request, never as a fallback for a missing checkout. Every
code-less run of an app is a run of one code verstr, :data:`CODELESS_VERSTR`
(``0.0.0-nocode``, ``.r2``, ... or a writer suffix), claimed like any run.
The record has no ``base_commit`` and carries ``codeless: true``, so rerun,
restore, export and diff refuse it as having no code snapshot.
"""
import collections

from vmn_exp.sdk import APP_NAME_ENV
from vmn_exp.sdk.create import RecordSource

CODELESS_VERSTR = "0.0.0-nocode"
CODELESS_KEY = "codeless"

# What a code-less source reaches for: ``default_storage()`` (the store the
# environment names), ``pick_parent(storage, app, parent, nested)``,
# ``capture_env(capture_env) -> env dict or None``, ``now() -> ISO time`` and
# ``lock``, a context-manager factory held while claiming.
CodelessIO = collections.namedtuple(
    "CodelessIO", "default_storage pick_parent capture_env now lock")


def codeless_source(app_name, parent, nested, storage, capture_env, env, io):
    """The :class:`RecordSource` of a run with no code; *env* is the process
    environment (a mapping), *io* a :data:`CodelessIO`."""
    app_name = app_name or env.get(APP_NAME_ENV)
    if not app_name:
        raise ValueError(
            "A run without code needs its app named: pass app_name= or set "
            f"{APP_NAME_ENV}.")
    if storage is None:
        storage = io.default_storage()
    template = {"app_name": app_name, "timestamp": io.now(), "note": None, CODELESS_KEY: True}
    run_env = io.capture_env(capture_env)
    parent = io.pick_parent(storage, app_name, parent, nested)
    return RecordSource(app_name, storage, CODELESS_VERSTR, template, parent, run_env,
                        None, io.lock, {})
