"""Argparse setup of the ``vmn-exp model`` command (handlers: ``registry/cli.py``)."""
from __future__ import annotations

from vmn_exp.core.storage_resolve import add_storage_flags
from vmn_exp.registry.names import KINDS


def _add_storage_args(parser):
    """Add common storage flags to a subcommand parser."""
    parser.add_argument(
        "--dir",
        default=None,
        help="Experiment storage directory (overrides VMN_EXPERIMENT_DIR)",
    )
    add_storage_flags(parser)


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
    preg = msub.add_parser("register", help="Register a new model or dataset version")
    preg.add_argument("model_name", help="Model (or dataset) name")
    preg.add_argument(
        "-v", "--version",
        dest="version_ref",
        default=None,
        help="Run ref (verstr, @N, prefix) to link; or --uri for a reference dataset",
    )
    preg.add_argument("--kind", choices=KINDS, default="model", help="model (default) or dataset")
    preg.add_argument(
        "--uri", default=None,
        help="Reference dataset location (local path is hashed); needs --kind dataset",
    )
    preg.add_argument("--digest", default=None, help="Dataset digest (sha256:<hex>)")
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
    plist.add_argument("--kind", choices=KINDS, default=None, help="Only models or only datasets")
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
