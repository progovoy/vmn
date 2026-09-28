"""Built-in plugin: register experiment, snapshot and ui CommandSpecs.

This module is on the EXPERIMENTS side of the boundary (classified via
EXPERIMENTS_GLOBS in tests/test_architecture_boundary.py).  It is loaded
by ``version_stamp.cli.plugins`` via importlib — not via a direct import — so
the AST-level boundary scanner never sees a stamping→experiments edge.

On import this module:
  1. Registers CommandSpecs for ``experiment``/``exp``, ``snapshot``, and
     ``ui`` in the plugin_api registry.
  2. Registers a dev-version loader so that ``output._goto_dev_version`` can
     restore a dev-version snapshot without importing this module directly.
"""
from __future__ import annotations

import os

from version_stamp.api import (
    VMN_LOGGER,
    CommandSpec,
    _get_repo_status,
    find_command,
    register_command,
    register_dev_version_loader,
)


# ---------------------------------------------------------------------------
# Argparse helpers (moved from version_stamp.cli.args)
# ---------------------------------------------------------------------------

def _add_snapshot_parser(subprasers):  # noqa: N802
    psnap = subprasers.add_parser(
        "snapshot",
        help="Create and manage local snapshots of uncommitted/unpushed changes",
    )
    psnap.set_defaults(strict_version=False)
    psnap.add_argument(
        "action",
        nargs="?",
        default="create",
        choices=["create", "list", "show", "note", "diff", "export", "restore"],
        help="Snapshot action: create (default), list, show, note, diff, export, restore",
    )
    psnap.add_argument("name", help="The application's name")
    psnap.add_argument("-v", "--version", default=None, required=False,
                       help="The dev version string (for show/note/diff/export actions)")
    psnap.add_argument("--note", default=None, required=False,
                       help="A description note for the snapshot")
    psnap.add_argument("--store", default=None, required=False,
                       help="Remote snapshot store URI "
                            "(s3://bucket/prefix, gs://..., az://..., file:///dir)")
    psnap.add_argument("--bucket", default=None, required=False,
                       help="S3 bucket name (shorthand for --store s3://BUCKET/PREFIX)")
    psnap.add_argument("--endpoint-url", default=None, required=False,
                       help="Custom S3 endpoint URL (for MinIO, DigitalOcean Spaces, etc.)")
    psnap.add_argument("--prefix", default="vmn-snapshots", required=False,
                       help="S3 key prefix for snapshot storage (default: vmn-snapshots)")
    psnap.add_argument("--to", default=None, required=False,
                       help="Second version for diff comparison (or 'current' for working state)")
    psnap.add_argument("--tool", default=None, required=False,
                       help="External diff tool (e.g., bcompare, meld, vimdiff). "
                            "Falls back to git config diff.tool")
    psnap.add_argument("-o", "--output", default=None, required=False,
                       help="Output path for export (default: {verstr}.tar.gz)")
    psnap.add_argument("--meta", action="append", default=None, required=False,
                       help="Key=value metadata pair (can be specified multiple times)")
    psnap.add_argument("--meta-file", default=None, required=False,
                       help="Path to YAML file containing metadata key-value pairs")
    psnap.add_argument("--filter", action="append", default=None, required=False,
                       help="Filter snapshots by key=value metadata "
                            "(for list action, can be repeated)")
    psnap.add_argument("--verbose", action="store_true", default=False,
                       help="Show full ISO timestamps in list output")
    psnap.add_argument("--latest", action="store_true", default=False,
                       help="Use the most recent snapshot (for show/note/diff/export)")
    psnap.add_argument("--last", type=int, default=None,
                       help="Show only the N most recent snapshots (for list)")


EXPERIMENT_ACTIONS = [
    "create", "run", "add", "list", "show", "compare", "diff", "restore",
    "export", "prune", "tag", "archive", "unarchive", "import-mlflow", "watch",
]


def _add_experiment_parser(subprasers, name):  # noqa: N802
    pexp = subprasers.add_parser(
        name, help="Experiment tracking for reproducible research"
    )
    pexp.set_defaults(strict_version=False)
    pexp.add_argument(
        "action", nargs="?", default="create",
        choices=EXPERIMENT_ACTIONS,
        help="Experiment action (default: create)",
    )
    pexp.add_argument("name", help="The application's name")
    pexp.add_argument("refs", nargs="*", default=None,
                      help="tag/archive/unarchive: run refs (verstr, prefix, @N, latest); "
                           "tag also takes key=value pairs")
    pexp.add_argument("--name", dest="run_name", default=None,
                      help="create/run: a human-readable name for the run")
    pexp.add_argument("--new-app", action="store_true", default=False,
                      help="create/run: confirm that this app name is genuinely new when "
                           "other vmn apps already exist in this repo")
    pexp.add_argument("--remove", action="append", default=None,
                      help="tag: remove this tag key (repeatable)")
    pexp.add_argument("--archived", action="store_true", default=False,
                      help="list: include archived runs")
    pexp.add_argument("-v", "--version", action="append", default=None,
                      help="Version string(s). Repeatable for compare; prune deletes exactly "
                           "the named run(s) instead of applying --keep/--older-than.")
    pexp.add_argument("--note", default=None, help="Note or description")
    pexp.add_argument("-f", "--file", default=None,
                      help="YAML file with structured notes/params")
    pexp.add_argument("--metrics", nargs="*", default=None,
                      help="Metrics as key=value pairs (e.g., loss=0.34 acc=0.91)")
    pexp.add_argument("--attach", default=None, help="File to attach as artifact")
    pexp.add_argument("--sort", default=None, help="Sort list by metric name")
    pexp.add_argument("--top", type=int, default=None,
                      help="Show top N results in list")
    pexp.add_argument("--last", type=int, default=None,
                      help="Use the N most recent experiments (for list/compare)")
    pexp.add_argument("--latest", action="store_true", default=False,
                      help="Use the most recent experiment (for show/compare/restore/export)")
    pexp.add_argument("--tool", default=None,
                      help="External diff tool for compare. Falls back to git config diff.tool")
    pexp.add_argument("-o", "--output", default=None, help="Output path for export")
    pexp.add_argument("--keep", type=int, default=None,
                      help="Keep latest N experiments (for prune)")
    pexp.add_argument("--older-than", default=None,
                      help="Prune experiments older than duration (e.g., 30d)")
    pexp.add_argument("--dry-run", dest="dry_run", action="store_true", default=False,
                      help="prune: print what would be deleted, delete nothing")
    pexp.add_argument("--force", action="store_true", default=False,
                      help="prune: also delete runs that are still running")
    pexp.add_argument("--local-only", action="store_true", default=False,
                      help="prune: delete local copies only, keep the remote (S3) ones")
    pexp.add_argument("--protect-tag", dest="protect_tag", action="append", default=None,
                      help="prune: never delete a run carrying this tag key (repeatable)")
    pexp.add_argument("--full-log", action="store_true", default=False,
                      help="show: print every log entry (default: the last 50)")
    pexp.add_argument("--query", default=None,
                      help="list: filter rows by query (e.g. 'metrics.loss < 0.5'); "
                           "prune: select candidates by query (dry-run unless --yes/-y)")
    pexp.add_argument("--yes", "-y", action="store_true", default=False,
                      help="prune --query: confirm deletion")
    pexp.add_argument("--json", action="store_true", default=False,
                      help="list/show: print machine-readable JSON")
    pexp.add_argument("--from-snapshot", default=None,
                      help="Path to vmn_metadata.yml or directory containing it. "
                           "Creates experiment from exported snapshot (no git required). "
                           "Falls back to VMN_SNAPSHOT_METADATA env var.")
    pexp.add_argument("--no-env", dest="capture_env", action="store_false", default=None,
                      help="create/run: skip environment capture (packages, python, platform). "
                           "Overrides VMN_CAPTURE_ENV and conf capture_env settings.")
    pexp.add_argument("--input", action="append", dest="inputs", default=None,
                      metavar="[NAME=]URI[#DIGEST]",
                      help="create/run/add: record a dataset or artifact input. "
                           "Optional name= prefix and #digest suffix. Repeatable.")
    pexp.add_argument("--experiment-dir", default=None,
                      help="Write experiments to this directory instead of local .vmn/. "
                           "Falls back to VMN_EXPERIMENT_DIR env var.")
    pexp.add_argument("--writer-id", default=None,
                      help="Unique writer ID for this process (default: VMN_WRITER_ID or hostname).")
    pexp.add_argument("--sync-interval", type=int, default=30,
                      help="Seconds between S3 metric syncs during 'run' (default: 30).")
    pexp.add_argument("--heartbeat-interval", type=int, default=30,
                      help="Seconds between run-state heartbeats during 'run' (default: 30).")
    pexp.add_argument("--kill-grace-sec", type=float, default=None,
                      help="Seconds a child gets to exit after a forwarded signal "
                           "before it is killed during 'run'.")
    pexp.add_argument("--system-metrics", action="store_true", default=False,
                      help="Record the child process tree's CPU/memory as sys_* metrics "
                           "during 'run'. Needs 'pip install vmn-exp-sdk[sysmetrics]'.")
    pexp.add_argument("--interval", type=float, default=None,
                      help="watch: re-check every N seconds (default: check once, for cron)")
    pexp.add_argument("--within", default=None,
                      help="watch: only alert transitions newer than this (e.g. 6h, 1d; "
                           "default 1d)")
    pexp.add_argument("--parent", default=None,
                      help="Parent experiment for a nested run.")
    pexp.add_argument("--store", default=None,
                      help="Storage URI: s3://bucket/prefix, gs://..., az://..., "
                           "file:///dir (or VMN_EXPERIMENT_STORE)")
    pexp.add_argument("--bucket", default=None,
                      help="S3 bucket name (shorthand for --store s3://BUCKET/PREFIX)")
    pexp.add_argument("--endpoint-url", default=None, help="Custom S3 endpoint URL")
    pexp.add_argument("--prefix", default="vmn-experiments", help="S3 key prefix")
    # import-mlflow flags
    _mlf = pexp.add_mutually_exclusive_group()
    _mlf.add_argument("--mlruns", default=None, metavar="DIR",
                      help="import-mlflow: path to mlruns/ FileStore directory")
    _mlf.add_argument("--tracking-uri", default=None, metavar="URI",
                      help="import-mlflow: MLflow tracking server URI "
                           "(requires mlflow-skinny)")
    pexp.add_argument("--experiment", action="append", default=None,
                      metavar="NAME_OR_ID",
                      help="import-mlflow: include only this experiment (repeatable)")
    pexp.add_argument("--skip-artifacts", action="store_true", default=False,
                      help="import-mlflow: do not copy local artifacts")
    pexp.add_argument("--include-deleted", action="store_true", default=False,
                      help="import-mlflow: include deleted/trashed runs")
    pexp.add_argument("--workers", type=int, default=8,
                      help="import-mlflow: parallel import workers (default: 8)")


def _add_ui_parser(subprasers):  # noqa: N802
    pui = subprasers.add_parser(
        "ui", help="Serve the vmn web UI (experiments, stamp tree, actions)"
    )
    pui.add_argument("--host", default="127.0.0.1", help="Bind address")
    pui.add_argument("--port", type=int, default=8265, help="Port (default 8265)")
    pui.add_argument("--allowed-host", action="append", default=None,
                     help="Extra hostname clients may reach the server by (repeatable).")
    pui.add_argument("--token", default=None,
                     help="Bearer token required for API access (or VMN_UI_TOKEN env)")
    pui.add_argument("--data-dir", default=None,
                     help="Server data dir for the workspace registry and index "
                          "(default: ~/.vmn-ui)")
    pui.add_argument("--repo", action="append", default=None,
                     help="Attach a local checkout as a workspace (repeatable)")
    pui.add_argument("--store", default=None,
                     help="Read-only experiment store URI (s3://, gs://, az://, file://)")
    pui.add_argument("--s3-bucket", default=None, help="Read-only S3 experiment source")
    pui.add_argument("--s3-prefix", default=None, help="S3 key prefix")
    pui.add_argument("--endpoint-url", default=None, help="Custom S3 endpoint URL")
    pui.add_argument("--read-only", action="store_true", default=False,
                     help="Disable all mutation endpoints")
    pui.add_argument("--no-browser", action="store_true", default=False,
                     help="Do not open a browser on start")
    pui.add_argument("--no-index", action="store_true", default=False,
                     help="Keep no on-disk read cache (the index lives in memory only)")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_snapshot(vmn_ctx):
    """Handle the ``vmn snapshot`` command. Moved from cli/commands.py."""
    from vmn_exp.snapshot import (
        _build_user_meta,
        _get_storage,
        _resolve_verstr,
        snapshot_create,
        snapshot_diff,
        snapshot_export,
        snapshot_list,
        snapshot_note,
        snapshot_restore,
        snapshot_show,
    )

    vmn_ctx.params["store"] = getattr(vmn_ctx.args, "store", None)
    vmn_ctx.params["bucket"] = getattr(vmn_ctx.args, "bucket", None)
    vmn_ctx.params["endpoint_url"] = getattr(vmn_ctx.args, "endpoint_url", None)
    vmn_ctx.params["prefix"] = getattr(vmn_ctx.args, "prefix", "vmn-snapshots")
    vmn_ctx.params["filter"] = getattr(vmn_ctx.args, "filter", None)
    vmn_ctx.params["verbose"] = getattr(vmn_ctx.args, "verbose", False)
    vmn_ctx.params["last"] = getattr(vmn_ctx.args, "last", None)

    conf_storage = getattr(vmn_ctx.vcs, "snapshot_storage", None) or {}
    if not vmn_ctx.params.get("bucket") and conf_storage.get("bucket"):
        vmn_ctx.params["bucket"] = conf_storage["bucket"]
    if not vmn_ctx.params.get("store") and conf_storage.get("uri"):
        vmn_ctx.params["store"] = conf_storage["uri"]
    if not vmn_ctx.params.get("prefix") or vmn_ctx.params["prefix"] == "vmn-snapshots":
        vmn_ctx.params["prefix"] = conf_storage.get("prefix", "vmn-snapshots")
    if not vmn_ctx.params.get("endpoint_url") and conf_storage.get("endpoint_url"):
        vmn_ctx.params["endpoint_url"] = conf_storage["endpoint_url"]

    expected_status = {"repo_tracked", "app_tracked"}
    optional_status = {
        "repos_exist_locally", "detached", "pending", "outgoing",
        "version_not_matched", "dirty_deps", "deps_synced_with_conf",
    }
    status = _get_repo_status(vmn_ctx.vcs, expected_status, optional_status)
    if status.error:
        app_name = vmn_ctx.vcs.name
        if "repo_tracked" not in status.state:
            VMN_LOGGER.error(
                "Repository not initialized. Run:\n\n"
                "  vmn init\n"
                f"  vmn stamp -r patch {app_name}\n"
            )
        elif "app_tracked" not in status.state:
            VMN_LOGGER.error(
                f"App '{app_name}' not initialized. Run:\n\n"
                f"  vmn stamp -r patch {app_name}\n"
            )
        return 1

    action = vmn_ctx.args.action

    if action in ("show", "note", "diff", "export", "restore"):
        latest = getattr(vmn_ctx.args, "latest", False)
        verstr = vmn_ctx.args.version
        to_ver = getattr(vmn_ctx.args, "to", None) if action == "diff" else None

        if verstr is None and not latest:
            latest = True
        if action == "diff" and to_ver is None:
            to_ver = "current"
            vmn_ctx.args.to = to_ver

        storage = _get_storage(vmn_ctx.vcs, vmn_ctx.params)

        resolved, err_msg = _resolve_verstr(
            storage, vmn_ctx.vcs.name, verstr, latest=latest
        )
        if err_msg:
            VMN_LOGGER.error(err_msg)
            return 1
        vmn_ctx.args.version = resolved

        if to_ver and to_ver != "current":
            resolved_to, err_msg = _resolve_verstr(storage, vmn_ctx.vcs.name, to_ver)
            if err_msg:
                VMN_LOGGER.error(err_msg)
                return 1
            vmn_ctx.args.to = resolved_to

    if action == "create":
        user_meta = _build_user_meta(
            vmn_ctx.args.meta, getattr(vmn_ctx.args, "meta_file", None)
        )
        return snapshot_create(vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.note,
                               user_meta=user_meta)
    elif action == "list":
        return snapshot_list(vmn_ctx.vcs, vmn_ctx.params)
    elif action == "show":
        return snapshot_show(vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version)
    elif action == "note":
        return snapshot_note(vmn_ctx.vcs, vmn_ctx.params,
                             vmn_ctx.args.version, vmn_ctx.args.note)
    elif action == "diff":
        return snapshot_diff(
            vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version,
            getattr(vmn_ctx.args, "to", None), getattr(vmn_ctx.args, "tool", None),
        )
    elif action == "export":
        return snapshot_export(
            vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version,
            getattr(vmn_ctx.args, "output", None),
        )
    elif action == "restore":
        return snapshot_restore(vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version)
    else:
        VMN_LOGGER.error("Unknown snapshot action: %s", action)
        return 1


def _handle_experiment(vmn_ctx):
    from vmn_exp.cli.experiment import handle_experiment
    return handle_experiment(vmn_ctx)


def _handle_ui(vmn_ctx):
    from vmn_exp.ui.cli import handle_ui
    return handle_ui(vmn_ctx.args)


# ---------------------------------------------------------------------------
# run_without_repo: experiment in from-snapshot mode (moved from entry.py)
# ---------------------------------------------------------------------------

def _exp_run_without_repo(args):
    """Experiment commands that work without a git repo.

    Handles: import-mlflow (always git-free) and from-snapshot mode.

    Returns an int exit code if handled, None to fall through to normal dispatch.
    """
    # import-mlflow is always git-free — intercept before from_snapshot check
    if (
        getattr(args, "command", None) in ("experiment", "exp")
        and getattr(args, "action", None) == "import-mlflow"
    ):
        from vmn_exp.importers.cli import import_mlflow_run_without_repo
        return import_mlflow_run_without_repo(args)

    from_snapshot = getattr(args, "from_snapshot", None) or os.environ.get(
        "VMN_SNAPSHOT_METADATA"
    )
    if args.command not in ("experiment", "exp") or not from_snapshot:
        return None

    from vmn_exp.cli.experiment import (
        _get_experiment_storage,
        experiment_add,
        experiment_compare,
        experiment_create,
        experiment_list,
        experiment_prune,
        experiment_run,
        experiment_show,
    )
    from vmn_exp.core.writer import merge_env_into_params

    if getattr(args, "writer_id", None):
        os.environ["VMN_WRITER_ID"] = args.writer_id

    params = {
        "store": getattr(args, "store", None),
        "bucket": getattr(args, "bucket", None),
        "prefix": getattr(args, "prefix", "vmn-experiments"),
        "endpoint_url": getattr(args, "endpoint_url", None),
        "experiment_dir": getattr(args, "experiment_dir", None),
    }
    merge_env_into_params(params)

    storage = _get_experiment_storage(None, params)
    action = args.action

    dispatch = {
        "create": experiment_create,
        "run": experiment_run,
        "add": experiment_add,
        "list": experiment_list,
        "show": experiment_show,
        "compare": experiment_compare,
        "prune": experiment_prune,
    }

    handler = dispatch.get(action)
    if handler is not None:
        return handler(None, params, storage, args)

    VMN_LOGGER.error(
        "Action '%s' requires a git repository "
        "(not available in --from-snapshot mode)",
        action,
    )
    return 1


# ---------------------------------------------------------------------------
# Dev-version loader: restores a dev/snapshot version without importing here
# ---------------------------------------------------------------------------

def _dev_version_loader(vcs, params, version):
    """Restore repo to state captured in a dev-version snapshot."""
    from vmn_exp.snapshot import (
        LocalSnapshotStorage,
        _restore_with_safety_net,
    )
    from vmn_exp.core.storage_resolve import store_uri
    from vmn_exp.storage.registry import open_store

    storage = LocalSnapshotStorage(vcs.vmn_root_path)
    metadata, patches = storage.load(vcs.name, version)

    if metadata is None:
        exp_storage = LocalSnapshotStorage(vcs.vmn_root_path, subdir="experiments")
        metadata, patches = exp_storage.load(vcs.name, version)

    if metadata is None:
        conf_storage = getattr(vcs, "snapshot_storage", None) or {}
        store = conf_storage.get("uri") or store_uri(conf_storage, "vmn-snapshots")
        if store:
            try:
                metadata, patches = open_store(store, subdir="snapshots").load(
                    vcs.name, version
                )
            except Exception:
                VMN_LOGGER.debug("Remote snapshot load failed", exc_info=True)

    if metadata is None:
        VMN_LOGGER.error("Snapshot %s not found locally or in configured storage", version)
        return 1

    return _restore_with_safety_net(vcs, params, metadata, patches)


# ---------------------------------------------------------------------------
# Register everything — idempotent so it can be called after a registry reset
# ---------------------------------------------------------------------------

def _register(spec) -> None:
    if find_command(spec.names[0]) is None:
        register_command(spec)


def register_snapshot() -> None:
    """The ``vmn.plugins`` entry point: ``vmn snapshot`` and dev-version goto.
    Idempotent, so it survives a registry reset."""
    _register(CommandSpec(
        names=("snapshot",),
        add_parser=_add_snapshot_parser,
        handle=_handle_snapshot,
        access="local",
        read_only_actions=frozenset({"list", "show", "diff", "export"}),
    ))
    register_dev_version_loader(_dev_version_loader)


def register_all() -> None:
    """Every command `vmn-exp` serves. Idempotent."""
    from vmn_exp.registry.cli import add_model_parser, model_run_without_repo

    register_snapshot()
    _register(CommandSpec(
        names=("experiment", "exp"),
        add_parser=lambda sp: (
            _add_experiment_parser(sp, "experiment"),
            _add_experiment_parser(sp, "exp"),
        ),
        handle=_handle_experiment,
        access="local",
        read_only_actions=frozenset(
            {"list", "show", "compare", "diff", "export", "import-mlflow", "watch"}
        ),
        split_after_double_dash=True,
        run_without_repo=_exp_run_without_repo,
    ))
    _register(CommandSpec(
        names=("ui",),
        add_parser=_add_ui_parser,
        handle=_handle_ui,
        access="local",
    ))
    _register(CommandSpec(
        names=("model",),
        add_parser=add_model_parser,
        handle=lambda ctx: model_run_without_repo(ctx.args),
        access="local",
        read_only_actions=frozenset({"list", "show", "resolve"}),
        run_without_repo=model_run_without_repo,
    ))
