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
from vmn_exp.registry.log import set_version_status
from vmn_exp.registry.names import valid_model_name, valid_alias_name, parse_ref
from vmn_exp.registry.store import ensure_model, register_version, list_models
from vmn_exp.registry.view import model_state, resolve_ref

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _get_storage(args):
    """Build experiment storage for registry operations from args / env."""
    return resolve_experiment_storage(
        dir=getattr(args, "dir", None),
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

    version_ref = getattr(args, "version_ref", None)
    if not version_ref:
        _LOG.error("Missing required -v / --version (run ref)")
        return 1

    app_name = getattr(args, "app", None)
    artifact_path = getattr(args, "artifact", None)
    description = getattr(args, "description", None)
    alias_name = getattr(args, "alias", None)

    verstr = _resolve_run_ref(storage, app_name, version_ref)
    if verstr is None:
        _LOG.error("Could not resolve run ref %r (app=%r)", version_ref, app_name)
        return 1

    run_ref = {"app": app_name, "verstr": verstr} if app_name else {"verstr": verstr}

    ensure_model(storage, model_name, description=description)
    n = register_version(
        storage,
        model_name,
        run_ref,
        artifact_path=artifact_path,
        description=description,
    )

    if alias_name is not None:
        if not valid_alias_name(alias_name):
            _LOG.error("Invalid alias name: %r", alias_name)
            return 1
        _set_alias(storage, model_name, alias_name, n)

    print(f"Registered {model_name} version {n} (run_ref={verstr!r})")
    return 0


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
    models = list_models(storage)
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
        }))
    else:
        print(f"model:    {model}")
        if app:
            print(f"app:      {app}")
        if verstr:
            print(f"verstr:   {verstr}")
        if artifact_path:
            print(f"artifact: {artifact_path}")
        if artifact_uri:
            print(f"uri:      {artifact_uri}")
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
    return _cmd_set_status(storage, args, "deleted")


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
# Argparse setup
# ---------------------------------------------------------------------------

def _add_storage_args(parser):
    """Add common storage flags to a subcommand parser."""
    parser.add_argument(
        "--dir",
        default=None,
        help="Experiment storage directory (overrides VMN_EXPERIMENT_DIR)",
    )
    parser.add_argument("--bucket", default=None, help="S3 bucket name")
    parser.add_argument("--prefix", default="vmn-experiments", help="S3 key prefix")
    parser.add_argument(
        "--endpoint-url",
        dest="endpoint_url",
        default=None,
        help="Custom S3 endpoint URL",
    )


def add_model_parser(subparsers):
    """Register the ``model`` command and its subcommands."""
    pmodel = subparsers.add_parser(
        "model",
        help="Model registry: register, alias, list, show, resolve, deprecate, delete",
    )
    pmodel.set_defaults(strict_version=False)

    msub = pmodel.add_subparsers(dest="action", metavar="action")
    msub.required = True

    # register
    preg = msub.add_parser("register", help="Register a new model version")
    preg.add_argument("model_name", help="Model name")
    preg.add_argument(
        "-v", "--version",
        dest="version_ref",
        required=True,
        help="Run ref (verstr, @N, prefix) to link",
    )
    preg.add_argument("--app", default=None, help="App name for run ref resolution")
    preg.add_argument("--artifact", default=None, help="Artifact path within the run")
    preg.add_argument("--alias", default=None, help="Also set this alias after registering")
    preg.add_argument("--description", default=None, help="Human-readable description")
    _add_storage_args(preg)

    # alias
    palias = msub.add_parser("alias", help="Manage model aliases")
    palias.add_argument("model_name", help="Model name")
    palias.add_argument("alias", help="Alias name")
    palias.add_argument("alias_version", nargs="?", help="Version number to point to")
    palias.add_argument(
        "--remove", action="store_true", default=False, help="Remove this alias"
    )
    palias.add_argument(
        "--expect",
        default=None,
        help="Expected current version (int) or 'none'; mismatch exits 1",
    )
    _add_storage_args(palias)

    # list
    plist = msub.add_parser("list", help="List registered models")
    plist.add_argument("--json", action="store_true", default=False)
    _add_storage_args(plist)

    # show
    pshow = msub.add_parser("show", help="Show model versions, statuses, and aliases")
    pshow.add_argument("model_name", help="Model name")
    pshow.add_argument("--json", action="store_true", default=False)
    _add_storage_args(pshow)

    # resolve
    presolve = msub.add_parser("resolve", help="Resolve a model ref to app/verstr/artifact")
    presolve.add_argument("model_name", help="Model ref (e.g. model@alias, model@3, model)")
    presolve.add_argument("--json", action="store_true", default=False)
    _add_storage_args(presolve)

    # deprecate
    pdep = msub.add_parser("deprecate", help="Mark a model version as deprecated")
    pdep.add_argument("model_name", help="Model name")
    pdep.add_argument("version_ref", help="Version number")
    _add_storage_args(pdep)

    # delete
    pdel = msub.add_parser("delete", help="Mark a model version as deleted")
    pdel.add_argument("model_name", help="Model name")
    pdel.add_argument("version_ref", help="Version number")
    _add_storage_args(pdel)

    return pmodel


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
    if desc:
        print(f"  Description: {desc}")
    print(f"  Versions: {len(state['versions'])}")
    for v in state["versions"]:
        aliases_str = f"  aliases={v['aliases']}" if v["aliases"] else ""
        print(f"    v{v['n']}  status={v['status']}{aliases_str}")
    if state["aliases"]:
        print(f"  Aliases: {state['aliases']}")
