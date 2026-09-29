"""Built-in plugin: register experiment, ui and model CommandSpecs.

This module is on the EXPERIMENTS side of the boundary (classified via
EXPERIMENTS_GLOBS in tests/test_architecture_boundary.py).  It is loaded
by ``version_stamp.cli.plugins`` via importlib — not via a direct import — so
the AST-level boundary scanner never sees a stamping→experiments edge.

On import this module:
  1. Registers CommandSpecs for ``experiment``/``exp``, ``ui``, ``sweep``
     and ``model`` in the plugin_api registry.
  2. Registers a dev-version loader so that ``output._goto_dev_version`` can
     restore a dev-version snapshot without importing this module directly.
"""
from __future__ import annotations

import os

from version_stamp.api import (
    VMN_LOGGER,
    CommandSpec,
    find_command,
    register_command,
    register_dev_version_loader,
)


# ---------------------------------------------------------------------------
# Argparse helpers (moved from version_stamp.cli.args)
# ---------------------------------------------------------------------------

EXPERIMENT_ACTIONS = [
    "create", "run", "add", "list", "show", "compare", "diff", "restore",
    "export", "prune", "tag", "archive", "unarchive", "import-mlflow", "watch",
    "lineage",
    "importance",
    "rewind",
    "rerun",
]


def _add_experiment_parser(subprasers, name):  # noqa: N802
    from vmn_exp.cli.define_metric_args import add_define_metric_flags
    from vmn_exp.cli.sweep.parser import add_experiment_storage_flags

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
                      help="list/importance: include archived runs")
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
    pexp.add_argument("--metric", default=None,
                      help="importance: the metric whose driving params to rank")
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
                      help="prune: print what would be deleted, delete nothing; "
                           "rerun: print the plan, create nothing")
    pexp.add_argument("--print", dest="print_only", action="store_true", default=False,
                      help="rerun: print the resolved command, cwd, code identity and a "
                           "recipe (with --json as JSON); runs and creates nothing")
    pexp.add_argument("--keep-worktree", action="store_true", default=False,
                      help="rerun: keep the workspace the run's code was restored into")
    pexp.add_argument("--worktree-dir", default=None, metavar="DIR",
                      help="rerun: restore the run's code here (missing or empty, "
                           "outside the repo; default: a fresh dir in $TMPDIR)")
    pexp.add_argument("--cwd", dest="rerun_cwd", default=None, metavar="PATH",
                      help="rerun: run the command here, relative to the restored app "
                           "root (default: the recorded cwd)")
    pexp.add_argument("--force", action="store_true", default=False,
                      help="prune: also delete runs that are still running")
    pexp.add_argument("--local-only", action="store_true", default=False,
                      help="prune: delete local copies only, keep the remote (S3) ones")
    pexp.add_argument("--protect-tag", dest="protect_tag", action="append", default=None,
                      help="prune: never delete a run carrying this tag key (repeatable)")
    pexp.add_argument("--full-log", action="store_true", default=False,
                      help="show: print every log entry (default: the last 50)")
    pexp.add_argument("--query", default=None,
                      help="list/importance: filter rows by query (e.g. 'metrics.loss < 0.5'); "
                           "prune: select candidates by query (dry-run unless --yes/-y)")
    pexp.add_argument("--yes", "-y", action="store_true", default=False,
                      help="prune --query: confirm deletion")
    pexp.add_argument("--json", action="store_true", default=False,
                      help="list/show/importance: print machine-readable JSON")
    pexp.add_argument("--from-snapshot", default=None,
                      help="Path to vmn_metadata.yml or directory containing it. "
                           "Records against a tree from 'vmn-exp export' (no git required). "
                           "Falls back to VMN_SNAPSHOT_METADATA env var.")
    pexp.add_argument("--no-env", dest="capture_env", action="store_false", default=None,
                      help="create/run: skip environment capture (packages, python, platform). "
                           "Overrides VMN_CAPTURE_ENV and conf capture_env settings.")
    pexp.add_argument("--input", action="append", dest="inputs", default=None,
                      metavar="[NAME=]URI[#DIGEST]",
                      help="create/run/add: record a dataset or artifact input. "
                           "Optional name= prefix and #digest suffix. Repeatable.")
    pexp.add_argument("--sync-interval", type=int, default=30,
                      help="Seconds between S3 metric syncs during 'run' (default: 30).")
    pexp.add_argument("--heartbeat-interval", type=int, default=30,
                      help="Seconds between run-state heartbeats during 'run' (default: 30).")
    pexp.add_argument("--kill-grace-sec", type=float, default=None,
                      help="Seconds a child gets to exit after a forwarded signal "
                           "before it is killed during 'run'.")
    pexp.add_argument("--no-capture-output", dest="capture_output", action="store_false",
                      default=True,
                      help="run: don't keep the command's stdout/stderr as the output.log "
                           "artifact (it still streams to the terminal).")
    pexp.add_argument("--output-cap-mb", type=float, default=None,
                      help="run: size cap of output.log; past it the first and last "
                           "halves are kept (default: VMN_EXP_OUTPUT_CAP_MB or 10).")
    pexp.add_argument("--no-system-metrics", dest="system_metrics", action="store_false",
                      default=None,
                      help="run: don't record the child process tree's CPU/memory/GPU as "
                           "sys_* metrics. Overrides VMN_SYSTEM_METRICS and conf "
                           "system_metrics settings.")
    pexp.add_argument("--interval", type=float, default=None,
                      help="watch: re-check every N seconds (default: check once, for cron)")
    pexp.add_argument("--within", default=None,
                      help="watch: only alert transitions newer than this (e.g. 6h, 1d; "
                           "default 1d)")
    pexp.add_argument("--depth", type=int, default=1,
                      help="lineage: follow links this many hops (default: 1)")
    pexp.add_argument("--parent", default=None,
                      help="Parent experiment for a nested run.")
    pexp.add_argument("--fork-from", default=None, metavar="REF",
                      help="create/run: start a new run with REF's metrics and params "
                           "(up to --fork-step; 'REF?_step=N' also works)")
    pexp.add_argument("--fork-step", type=int, default=None, metavar="N",
                      help="create/run: with --fork-from, copy history up to step N "
                           "(default: all of it)")
    pexp.add_argument("--step", type=int, default=None, metavar="N",
                      help="rewind: hide the run's history past step N")
    add_experiment_storage_flags(pexp)
    add_define_metric_flags(pexp)
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
    pui.add_argument("--read-only", action="store_true", default=False,
                     help="Disable all mutation endpoints")
    pui.add_argument("--no-browser", action="store_true", default=False,
                     help="Do not open a browser on start")
    pui.add_argument("--no-index", action="store_true", default=False,
                     help="Keep no on-disk read cache (the index lives in memory only)")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_experiment(vmn_ctx):
    from vmn_exp.cli.experiment import handle_experiment
    return handle_experiment(vmn_ctx)


def _add_sweep_parser(subparsers):
    from vmn_exp.cli.sweep.parser import add_sweep_parser
    return add_sweep_parser(subparsers)


def _handle_sweep(vmn_ctx):
    from vmn_exp.cli.sweep.handler import handle_sweep
    return handle_sweep(vmn_ctx)


def _handle_ui(vmn_ctx):
    from vmn_exp.ui.cli import handle_ui
    return handle_ui(vmn_ctx.args)


# ---------------------------------------------------------------------------
# run_without_repo: experiment in from-snapshot mode (moved from entry.py)
# ---------------------------------------------------------------------------

def _exp_run_without_repo(args):
    """Experiment commands that work without a git repo.

    Handles: run under VMN_MODE=disabled, import-mlflow (always git-free) and
    from-snapshot mode.

    Returns an int exit code if handled, None to fall through to normal dispatch.
    """
    is_experiment = getattr(args, "command", None) in ("experiment", "exp")
    action = getattr(args, "action", None)
    if is_experiment and action == "run":
        from vmn_exp.cli.run_disabled import exec_if_disabled
        result = exec_if_disabled(args)
        if result is not None:
            return result

    # import-mlflow is always git-free — intercept before from_snapshot check
    if is_experiment and action == "import-mlflow":
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
        experiment_rewind,
        experiment_run,
        experiment_show,
        experiment_storage_params,
    )

    dispatch = {
        "create": experiment_create,
        "run": experiment_run,
        "add": experiment_add,
        "list": experiment_list,
        "show": experiment_show,
        "compare": experiment_compare,
        "prune": experiment_prune,
        "rewind": experiment_rewind,
    }

    handler = dispatch.get(action)
    if handler is None:
        VMN_LOGGER.error(
            "Action '%s' requires a git repository "
            "(not available in --from-snapshot mode)",
            action,
        )
        return 1

    if getattr(args, "writer_id", None):
        os.environ["VMN_WRITER_ID"] = args.writer_id
    params = experiment_storage_params(None, args)
    return handler(None, params, _get_experiment_storage(None, params), args)


# ---------------------------------------------------------------------------
# Dev-version loader: restores a dev/snapshot version without importing here
# ---------------------------------------------------------------------------

def _dev_version_loader(vcs, params, version):
    """Restore repo to state captured in a dev-version snapshot."""
    from vmn_exp.cli.code_record import load_code_record
    from vmn_exp.cli.experiment import experiment_storage_params
    from vmn_exp.snapshot import _restore_with_safety_net

    record = load_code_record(vcs, experiment_storage_params(vcs, None), version)
    if record is None:
        return 1
    return _restore_with_safety_net(vcs, params, *record)


# ---------------------------------------------------------------------------
# Register everything — idempotent so it can be called after a registry reset
# ---------------------------------------------------------------------------

def _register(spec) -> None:
    if find_command(spec.names[0]) is None:
        register_command(spec)


def register_dev_version() -> None:
    """The ``vmn.plugins`` entry point: lets ``vmn goto`` restore dev versions.
    Idempotent, so it survives a registry reset."""
    register_dev_version_loader(_dev_version_loader)


def register_all() -> None:
    """Every command `vmn-exp` serves. Idempotent."""
    from vmn_exp.registry.cli import add_model_parser, model_run_without_repo

    register_dev_version()
    _register(CommandSpec(
        names=("experiment", "exp"),
        add_parser=lambda sp: (
            _add_experiment_parser(sp, "experiment"),
            _add_experiment_parser(sp, "exp"),
        ),
        handle=_handle_experiment,
        access="local",
        read_only_actions=frozenset(
            {"list", "show", "compare", "diff", "export", "import-mlflow", "watch",
             "lineage", "importance"}
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
        names=("sweep",),
        add_parser=_add_sweep_parser,
        handle=_handle_sweep,
        access="local",
        read_only_actions=frozenset({"status"}),
        split_after_double_dash=True,
    ))
    _register(CommandSpec(
        names=("model",),
        add_parser=add_model_parser,
        handle=lambda ctx: model_run_without_repo(ctx.args),
        access="local",
        read_only_actions=frozenset({"list", "show", "resolve"}),
        run_without_repo=model_run_without_repo,
    ))
