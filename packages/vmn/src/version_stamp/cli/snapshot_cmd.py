"""The built-in ``vmn snapshot [action] <app>`` command.

``add_arg_snapshot(subparsers)`` declares the parser; ``handle_snapshot(ctx)``
checks the app is stamped, opens the stores (``--store`` / ``--local``, see
:mod:`version_stamp.snapshot.stores`), resolves ``-v`` refs and dispatches to
the ``version_stamp.snapshot`` modules (imported lazily). ``show``/``export``/
``diff`` default to the latest snapshot; ``note``/``delete``/``restore`` need
``-v`` or ``--latest``.
``list``/``show``/``diff``/``export`` run without the repo lock
(``constants.READ_ONLY_ACTIONS``).
"""
from version_stamp.cli.constants import SNAPSHOT_ACTIONS
from version_stamp.core.logging import VMN_LOGGER

_FLAGS = (
    (("-v", "--version"), dict(default=None, help="Snapshot ref: verstr, unique prefix, @N or latest")),
    (("--latest",), dict(action="store_true", help="Use the most recent snapshot")),
    (("--note",), dict(default=None, help="A description note for the snapshot")),
    (("--meta",), dict(action="append", default=None, help="create: key=value metadata (repeatable)")),
    (("--meta-file",), dict(default=None, help="create: YAML file of metadata key-value pairs")),
    (("--store",), dict(default=None, help="Snapshot store URI (remote stores need vmn-exp)")),
    (("--local",), dict(action="store_true", help="Use the local store even if one is configured")),
    (("--filter",), dict(action="append", default=None, help="list: key=value metadata filter (repeatable)")),
    (("--last",), dict(type=int, default=None, help="list: only the N most recent snapshots")),
    (("--verbose",), dict(action="store_true", help="list: full ISO timestamps")),
    (("--json",), dict(action="store_true", dest="as_json", help="list/show: print JSON")),
    (("--to",), dict(default=None, help="diff: the other side (default: current working state)")),
    (("--tool",), dict(default=None, help="diff: external diff tool (default: git diff.tool)")),
    (("-o", "--output"), dict(default=None, help="export: output dir or .tar.gz (default: <verstr>.tar.gz)")),
    (("--force",), dict(action="store_true", help="restore: even if the safety snapshot drops untracked files")),
)


def add_arg_snapshot(subparsers):
    psnap = subparsers.add_parser(
        "snapshot", help="Save and restore uncommitted work as deterministic dev versions"
    )
    psnap.set_defaults(strict_version=False)
    psnap.add_argument(
        "action", nargs="?", default="create", choices=SNAPSHOT_ACTIONS,
        help=f"Snapshot action: {', '.join(SNAPSHOT_ACTIONS)} (create is the default)",
    )
    psnap.add_argument("name", help="The application's name")
    for flags, kwargs in _FLAGS:
        psnap.add_argument(*flags, **kwargs)


def _repo_status(vcs):
    from version_stamp.stamping.repo_status import (
        READ_ONLY_EXPECTED,
        READ_ONLY_OPTIONAL,
        _get_repo_status,
    )

    status = _get_repo_status(vcs, READ_ONLY_EXPECTED, READ_ONLY_OPTIONAL)
    if not status.error:
        return status
    if "repo_tracked" not in status.state:
        VMN_LOGGER.error(f"Repository not initialized. Run:\n\n  vmn stamp -r patch {vcs.name}\n")
    elif "app_tracked" not in status.state:
        VMN_LOGGER.error(f"App '{vcs.name}' not initialized. Run:\n\n  vmn stamp -r patch {vcs.name}\n")
    return None


def _params(vmn_ctx):
    args = vmn_ctx.args
    vmn_ctx.params.update(store=args.store, local=args.local, force=args.force)
    return vmn_ctx.params


def _resolve(records, app_name, args, default_latest):
    from version_stamp.snapshot.refs import resolve_snapshot_ref

    if args.version is None and not args.latest and not default_latest:
        VMN_LOGGER.error(f"snapshot {args.action} needs -v <ref> (or --latest)")
        return None
    verstr, err = resolve_snapshot_ref(records, app_name, args.version, latest=args.latest or args.version is None)
    if err:
        VMN_LOGGER.error(err)
    return verstr


def _ref_actions(vcs, params, args, stores):
    """``{action: (defaults to latest?, run(verstr))}`` of the actions taking a ref."""
    from version_stamp.snapshot import delete, diff, export, listing, restore

    return {
        "show": (True, lambda v: listing.snapshot_show(stores.records, vcs.name, v, args.as_json)),
        "note": (False, lambda v: listing.snapshot_note(stores.records, vcs.name, v, args.note)),
        "delete": (False, lambda v: delete.snapshot_delete(stores, vcs.name, v)),
        "restore": (False, lambda v: restore.snapshot_restore(vcs, params, stores, v)),
        "export": (True, lambda v: export.snapshot_export(vcs, stores, v, args.output)),
        "diff": (True, lambda v: diff.snapshot_diff(vcs, stores, v, to=args.to, tool=args.tool)),
    }


def _run_ref_action(vcs, params, args, stores):
    default_latest, run = _ref_actions(vcs, params, args, stores)[args.action]
    verstr = _resolve(stores.records, vcs.name, args, default_latest)
    return 1 if verstr is None else run(verstr)


def _create(vcs, args, stores, status):
    from version_stamp.snapshot.create import build_user_meta, snapshot_create

    try:
        user_meta = build_user_meta(args.meta, args.meta_file)
    except (ValueError, OSError) as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    return snapshot_create(vcs, stores, note=args.note, user_meta=user_meta, status=status)


def _list(vcs, args, stores):
    from version_stamp.snapshot.create import parse_meta_args
    from version_stamp.snapshot.listing import snapshot_list

    try:
        filters = parse_meta_args(args.filter)
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    return snapshot_list(stores.records, vcs.name, last=args.last, filters=filters,
                         verbose=args.verbose, as_json=args.as_json)


def _open_stores(vcs, params):
    from version_stamp.snapshot.stores import SnapshotStoreError, open_snapshot_stores

    try:
        return open_snapshot_stores(vcs, params)
    except SnapshotStoreError as exc:
        VMN_LOGGER.error(str(exc))
        return None


def handle_snapshot(vmn_ctx):
    vcs, args = vmn_ctx.vcs, vmn_ctx.args
    status = _repo_status(vcs)
    if status is None:
        return 1
    params = _params(vmn_ctx)
    stores = _open_stores(vcs, params)
    if stores is None:
        return 1
    if args.action == "create":
        return _create(vcs, args, stores, status)
    if args.action == "list":
        return _list(vcs, args, stores)
    return _run_ref_action(vcs, params, args, stores)
