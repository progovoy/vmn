"""CLI handlers for the ``vmn-exp model`` command (C7).

All model actions are git-free: the registry lives in experiment storage
(under the reserved pseudo-app ``vmn-registry``) and never needs a git repo.
``model_run_without_repo`` is registered as the ``run_without_repo`` hook of
the CommandSpec so every action short-circuits before the repo lock.

Storage resolution order (same as ``vmn-exp``):
  1. ``--dir`` flag
  2. ``VMN_EXPERIMENT_DIR`` environment variable
  3. repo root auto-detected from cwd (fixes visibility of SDK-registered models)
  4. ``--bucket`` / ``VMN_EXPERIMENT_BUCKET`` → S3 backend

Boundary: this module is EXPERIMENTS side; may only reach stamping via
``version_stamp.api``.
"""
from __future__ import annotations

import json
import logging

from vmn_exp.core.storage_resolve import resolve_experiment_storage
from vmn_exp.registry.log import set_alias as _set_alias
from vmn_exp.registry.log import remove_alias as _remove_alias
from vmn_exp.registry.datasets import copied_fields, reference_fields, register_dataset_version
from vmn_exp.registry.log import read_uses, set_version_status
from vmn_exp.registry.names import valid_model_name, valid_alias_name, parse_ref
from vmn_exp.registry.store import ensure_model, list_models, model_kind, register_version
from vmn_exp.registry.view import model_state, resolve_ref
from vmn_exp.registry.cli_parser import add_model_parser  # noqa: F401  (re-exported)

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _get_storage(args):
    """Build experiment storage for registry operations from args / env."""
    return resolve_experiment_storage(
        dir=getattr(args, "dir", None),
        store=getattr(args, "store", None),
        bucket=getattr(args, "bucket", None),
        prefix=getattr(args, "prefix", None),
        endpoint_url=getattr(args, "endpoint_url", None),
    )


# ---------------------------------------------------------------------------
# Individual command handlers
# ---------------------------------------------------------------------------

def _cmd_register(storage, args):
    model_name = getattr(args, "model_name", None)
    if not model_name or not valid_model_name(model_name):
        _LOG.error("Invalid model name: %r", model_name)
        return 1
    alias_name = getattr(args, "alias", None)
    if alias_name is not None and not valid_alias_name(alias_name):
        _LOG.error("Invalid alias name: %r", alias_name)
        return 1
    source = _register_source_error(args)
    if source:
        _LOG.error("%s", source)
        return 1

    try:
        n, origin = _register_version(storage, model_name, args)
    except (ValueError, FileNotFoundError) as exc:
        _LOG.error("%s", exc)
        return 1

    if alias_name is not None:
        _set_alias(storage, model_name, alias_name, n)

    print(f"Registered {model_name} version {n} ({origin})")
    return 0


def _register_source_error(args):
    """Why the register flags name no single source, else None."""
    version_ref, uri = getattr(args, "version_ref", None), getattr(args, "uri", None)
    if bool(version_ref) == bool(uri):
        return "Pass exactly one of -v/--version (a run) or --uri (a reference dataset)"
    if uri and getattr(args, "kind", None) != "dataset":
        return "--uri registers a reference dataset: add --kind dataset"
    return None


def _register_version(storage, model_name, args):
    """``(n, origin text)`` of the new (or deduped) version."""
    description = getattr(args, "description", None)
    uri = getattr(args, "uri", None)
    if uri:
        fields = reference_fields(uri, getattr(args, "digest", None))
        n = register_dataset_version(storage, model_name, fields, description=description)
        return n, f"uri={fields['uri']!r}"

    app_name = getattr(args, "app", None)
    verstr = _resolve_run_ref(storage, app_name, args.version_ref)
    if verstr is None:
        raise ValueError(f"Could not resolve run ref {args.version_ref!r} (app={app_name!r})")
    run_ref = {"app": app_name, "verstr": verstr} if app_name else {"verstr": verstr}
    artifact_path = getattr(args, "artifact", None)
    if getattr(args, "kind", None) == "dataset":
        fields = copied_fields(storage, run_ref, artifact_path, getattr(args, "digest", None))
        n = register_dataset_version(storage, model_name, fields, description=description)
    else:
        ensure_model(storage, model_name, description=description)
        n = register_version(storage, model_name, run_ref, artifact_path=artifact_path,
                             description=description)
    return n, f"run_ref={verstr!r}"


def _cmd_alias(storage, args):
    model_name = getattr(args, "model_name", None)
    alias = getattr(args, "alias", None)
    remove = getattr(args, "remove", False)
    expect = _parse_expect(getattr(args, "expect", None))

    if not model_name:
        _LOG.error("Missing model name")
        return 1
    if not alias or not valid_alias_name(alias):
        _LOG.error("Invalid alias name: %r", alias)
        return 1

    try:
        if remove:
            _remove_alias(storage, model_name, alias, expect=expect)
            print(f"Removed alias {alias!r} from {model_name}")
        else:
            version_raw = getattr(args, "alias_version", None)
            if not version_raw:
                _LOG.error("Missing version argument for alias command")
                return 1
            try:
                version = int(version_raw)
            except (ValueError, TypeError):
                _LOG.error("Version must be an integer, got %r", version_raw)
                return 1
            _set_alias(storage, model_name, alias, version, expect=expect)
            print(f"Alias {alias!r} -> {model_name} version {version}")
    except ValueError as exc:
        _LOG.error("%s", exc)
        return 1

    return 0


def _cmd_list(storage, args):
    models = list_models(storage, kind=getattr(args, "kind", None))
    if getattr(args, "json", False):
        print(json.dumps(models))
    else:
        for m in models:
            print(m)
    return 0


def _cmd_show(storage, args):
    model_name = getattr(args, "model_name", None)
    if not model_name:
        _LOG.error("Missing model name")
        return 1
    try:
        state = model_state(storage, model_name)
    except Exception as exc:
        _LOG.error("Cannot show model %r: %s", model_name, exc)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(state))
    else:
        _print_model_state(model_name, state)
    return 0


def _cmd_resolve(storage, args):
    ref = getattr(args, "model_name", None)
    if not ref:
        _LOG.error("Missing model ref")
        return 1
    try:
        meta = resolve_ref(storage, ref)
    except KeyError as exc:
        _LOG.error("%s", exc)
        return 1

    model, _, _ = parse_ref(ref)
    run_ref = meta.get("run_ref", {})
    app = run_ref.get("app") if isinstance(run_ref, dict) else None
    verstr = run_ref.get("verstr") if isinstance(run_ref, dict) else None
    artifact_path = meta.get("artifact_path")
    artifact_uri = None

    if artifact_path and app and verstr:
        try:
            artifact_uri = storage.artifact_uri(app, verstr, artifact_path)
        except Exception:
            pass

    if getattr(args, "json", False):
        print(json.dumps({
            "model": model,
            "n": meta.get("n"),
            "app": app,
            "verstr": verstr,
            "artifact_path": artifact_path,
            "artifact_uri": artifact_uri,
            "kind": model_kind(storage, model),
            "uri": meta.get("uri"),
            "digest": meta.get("digest"),
        }))
    else:
        print(f"model:    {model}")
        if app:
            print(f"app:      {app}")
        if verstr:
            print(f"verstr:   {verstr}")
        if artifact_path:
            print(f"artifact: {artifact_path}")
        uri = artifact_uri or meta.get("uri")
        if uri:
            print(f"uri:      {uri}")
        if meta.get("digest"):
            print(f"digest:   {meta['digest']}")
    return 0


def _cmd_set_status(storage, args, status: str):
    """Shared body for deprecate and delete."""
    model_name = getattr(args, "model_name", None)
    version_raw = getattr(args, "version_ref", None)
    try:
        version = int(version_raw)
    except (ValueError, TypeError):
        _LOG.error("Version must be an integer, got %r", version_raw)
        return 1
    try:
        set_version_status(storage, model_name, version, status)
    except (ValueError, KeyError) as exc:
        _LOG.error("%s", exc)
        return 1
    print(f"{status.capitalize()}d {model_name} version {version}")
    return 0


def _cmd_deprecate(storage, args):
    return _cmd_set_status(storage, args, "deprecated")


def _cmd_delete(storage, args):
    rc = _cmd_set_status(storage, args, "deleted")
    if rc == 0:
        _warn_consumers(storage, args.model_name, int(args.version_ref))
    return rc


def _warn_consumers(storage, model_name, version):
    users = read_uses(storage, model_name).get(version, [])
    if users:
        _LOG.warning(
            "%s version %d was used by %d runs; their lineage still names it.",
            model_name, version, len(users),
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def model_run_without_repo(args):
    """Handle all ``vmn-exp model`` actions without a git repo.

    Returns an int exit code (0 = ok, 1 = error).  Always returns an int
    (never None) because every model action is repo-free.
    """
    storage = _get_storage(args)

    dispatch = {
        "register": _cmd_register,
        "alias": _cmd_alias,
        "list": _cmd_list,
        "show": _cmd_show,
        "resolve": _cmd_resolve,
        "deprecate": _cmd_deprecate,
        "delete": _cmd_delete,
    }

    handler = dispatch.get(getattr(args, "action", None))
    if handler is None:
        _LOG.error("Unknown model action: %r", getattr(args, "action", None))
        return 1
    return handler(storage, args)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_run_ref(storage, app_name, ref):
    """Resolve *ref* to a canonical verstr.

    A plain verstr (no @, no -dev.) is returned as-is.  @N / prefix / "latest"
    use experiment_refs.resolve_experiment when an app_name is given.
    """
    if not ref:
        return None
    from vmn_exp.core.refs import _needs_listing, resolve_experiment
    if not _needs_listing(storage, app_name, ref, False):
        return ref
    if not app_name:
        _LOG.error("Run ref %r requires --app to resolve via experiment index", ref)
        return None
    verstr, err = resolve_experiment(storage, app_name, ref)
    if err:
        return None
    return verstr


def _parse_expect(raw):
    """Parse --expect value: int, "none", or None (not given)."""
    if raw is None:
        return None
    if raw.lower() == "none":
        return "none"
    try:
        return int(raw)
    except ValueError:
        return raw


def _print_model_state(model_name, state):
    """Human-readable model state output."""
    header = state.get("header") or {}
    desc = header.get("description")
    print(f"Model: {model_name}")
    print(f"  Kind: {state.get('kind') or 'model'}")
    if desc:
        print(f"  Description: {desc}")
    print(f"  Versions: {len(state['versions'])}")
    for v in state["versions"]:
        aliases_str = f"  aliases={v['aliases']}" if v["aliases"] else ""
        print(f"    v{v['n']}  status={v['status']}{aliases_str}")
    if state["aliases"]:
        print(f"  Aliases: {state['aliases']}")
