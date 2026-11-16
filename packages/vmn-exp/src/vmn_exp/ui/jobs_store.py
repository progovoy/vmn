"""In-process job actions for store workspaces (plan 11 §7.1).

A store workspace has no checkout to run ``vmn`` in, so its metadata edits
call the git-free functions the CLI calls (``core/manage.py``,
``core/fork.py:rewind_run``, ``registry/*``) against the workspace storage,
with the server's own access. Prune, delete, push and git actions are never
offered here: they stay CLI-only, under the user's own access.

:func:`build_store_action` validates a request into a :class:`StoreAction`;
``action.run(storage, hint, now)`` performs it, returns its log text, raises on
failure, and calls ``hint(app, verstr)`` for every run record it touched.
"""
from dataclasses import dataclass
from typing import Callable, List

from vmn_exp.core.fork import rewind_run
from vmn_exp.core.metric_compact import rebuild_compacted
from vmn_exp.core.manage import set_archived, tag_run
from vmn_exp.core.status import load_run_state
from vmn_exp.core.writer import append_to_log, create_log_entry, flush_log, get_writer_id
from vmn_exp.registry.log import set_alias, set_version_status
from vmn_exp.registry.names import valid_model_name
from vmn_exp.registry.store import ensure_model, register_version
from vmn_exp.ui.jobs_exp_meta import (
    _valid_verstr,
    exp_archive_command,
    exp_rewind_command,
    exp_tag_command,
)
from vmn_exp.ui.jobs_models import validate_alias_body, validate_register_body


@dataclass
class StoreAction:
    command: List[str]  # what the job shows as its command
    perform: Callable  # (storage, hint, now: when runs' status is judged) -> log text

    def run(self, storage, hint, now):
        return self.perform(storage, hint, now)


class StoreActionError(RuntimeError):
    pass


def _require_run(storage, app_name, verstr):
    if not storage.exists(app_name, verstr):
        raise StoreActionError(f"Experiment '{verstr}' not found for {app_name}")


def _tag(app_name, body, env, host):
    _, err = exp_tag_command(app_name, body)
    if err:
        return None, err
    verstr = body["verstr"]

    def perform(storage, hint, now):
        if not tag_run(storage, app_name, verstr, body.get("set") or {}, body.get("remove") or [],
                       writer=get_writer_id(env, host)):
            raise StoreActionError(f"Experiment '{verstr}' not found for {app_name}")
        hint(app_name, verstr)
        return verstr

    return StoreAction(["exp_tag", app_name, verstr], perform), None


def _note(app_name, body, env, host):
    verstr, note = body.get("verstr"), body.get("note")
    if not _valid_verstr(verstr) or not isinstance(note, str):
        return None, "verstr and note are required"

    def perform(storage, hint, now):
        _require_run(storage, app_name, verstr)
        writer = get_writer_id(env, host)
        append_to_log(storage, app_name, verstr, create_log_entry("note", text=note), writer)
        flush_log(storage, app_name, verstr, writer)
        hint(app_name, verstr)
        return f"Added note to {verstr}"

    return StoreAction(["note", app_name, verstr], perform), None


def _archive(archived):
    verb = "archive" if archived else "unarchive"

    def build(app_name, body, env, host):
        _, err = exp_archive_command(verb, app_name, body)
        if err:
            return None, err
        verstrs = list(body["verstrs"])

        def perform(storage, hint, now):
            for verstr in verstrs:
                if not set_archived(storage, app_name, verstr, archived):
                    raise StoreActionError(f"Experiment '{verstr}' not found for {app_name}")
                hint(app_name, verstr)
            return "\n".join(verstrs)

        return StoreAction([f"exp_{verb}", app_name, *verstrs], perform), None

    return build


def _rewind(app_name, body, env, host):
    _, err = exp_rewind_command(app_name, body)
    if err:
        return None, err
    verstr, step = body["verstr"], body["step"]

    def perform(storage, hint, now):
        _require_run(storage, app_name, verstr)
        writer = get_writer_id(env, host)
        rewind_run(storage, app_name, verstr, step,
                   load_run_state(storage, app_name, verstr) or {}, now, writer=writer)
        flush_log(storage, app_name, verstr, writer)
        rebuild_compacted(storage, app_name, verstr)
        hint(app_name, verstr)
        return f"rewound {verstr} to step {step}"

    return StoreAction(["exp_rewind", app_name, verstr, str(step)], perform), None


def _model_name(body):
    model = body.get("model")
    return model if isinstance(model, str) and valid_model_name(model) else None


def _model_register(app_name, body, env, host):
    model = _model_name(body)
    if model is None:
        return None, "A valid model name is required"
    fields, err = validate_register_body(body)
    if err:
        return None, err

    def perform(storage, hint, now):
        ensure_model(storage, model, description=fields["description"])
        n = register_version(storage, model, fields["run"],
                             artifact_path=fields["artifact_path"],
                             description=fields["description"])
        if fields["alias"]:
            set_alias(storage, model, fields["alias"], n, env=env, host=host)
        return f"Registered {model} version {n}"

    return StoreAction(["model_register", model], perform), None


def _model_alias(app_name, body, env, host):
    model = _model_name(body)
    if model is None:
        return None, "A valid model name is required"
    fields, err = validate_alias_body(body)
    if err:
        return None, err

    def perform(storage, hint, now):
        set_alias(storage, model, fields["alias"], fields["version"], expect=fields["expect"],
                  env=env, host=host)
        return f"Alias {fields['alias']!r} -> {model} version {fields['version']}"

    return StoreAction(["model_alias", model, fields["alias"]], perform), None


def _model_deprecate(app_name, body, env, host):
    model, version = _model_name(body), body.get("version")
    if model is None:
        return None, "A valid model name is required"
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        return None, "'version' must be a positive integer"

    def perform(storage, hint, now):
        set_version_status(storage, model, version, "deprecated", env=env, host=host)
        return f"Deprecated {model} version {version}"

    return StoreAction(["model_deprecate", model, str(version)], perform), None


STORE_ACTIONS = {
    "exp_tag": _tag,
    "note": _note,
    "exp_archive": _archive(True),
    "exp_unarchive": _archive(False),
    "exp_rewind": _rewind,
    "model_register": _model_register,
    "model_alias": _model_alias,
    "model_deprecate": _model_deprecate,
}


def run_refreshing_once(actions, storage, touched, now):
    """Run *actions* on *storage*, their log text; then ``touched(app)`` once
    for each app whose runs they changed, even when one fails. Refreshing an
    app's index re-lists the app, so a refresh per run would make a batch of
    runs quadratic."""
    apps = {}

    def hint(app_name, verstr):
        apps[app_name] = None

    try:
        return "\n".join(action.run(storage, hint, now) for action in actions)
    finally:
        for app_name in apps:
            touched(app_name)


def build_store_action(action, app_name, body, env, host):
    """``(StoreAction, None)`` or ``(None, error)`` for a store workspace; its
    writes are the writer's of *env* and *host*."""
    builder = STORE_ACTIONS.get(action)
    if builder is None:
        return None, f"Action '{action}' is not available on a store workspace"
    return builder(app_name, body or {}, env, host)
