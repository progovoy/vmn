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
    register_snapshot_store_opener,
)
from vmn_exp.cli.exp_parser.actions import EXPERIMENT_ACTIONS  # noqa: F401  (main.py, tests)


def _add_experiment_parser(subparsers, name):
    from vmn_exp.cli.exp_parser.build import add_experiment_parser
    return add_experiment_parser(subparsers, name)


def _add_ui_parser(subprasers):  # noqa: N802
    from vmn_exp.cli import views

    pui = subprasers.add_parser(
        "ui", help="Serve the vmn web UI (experiments, stamp tree, actions)"
    )
    pui.add_argument("ui_args", nargs="*",
                     metavar="cache resync|rebuild | onboarding | backup <path> | diag",
                     help="Maintenance: 'cache resync' re-checks every record of the "
                          "cache, 'cache rebuild' rebuilds it; 'onboarding' prints the "
                          "BYO-bucket IAM policy for --store; 'backup <path>' copies the "
                          "SQLite control plane (Postgres: prints the pg_dump command); "
                          "'diag' takes a diagnostic dump of a running server "
                          "(--url, --pid or --summarize FILE)")
    pui.add_argument("--workspace", default=None,
                     help="cache: the workspace to resync (default: every one)")
    pui.add_argument("--config", default=None,
                     help="Server config file (server.yml); flags override its values")
    pui.add_argument("--db", default=None,
                     help="Control-plane DB DSN (sqlite:///path or postgresql://...; or "
                          "VMN_UI_DB). Keeps the workspace registry in the DB; "
                          "Postgres also holds the shared cache for replicas")
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
    pui.add_argument("--keep-warm", dest="keep_warm", action="store_const", const=True,
                     default=None,
                     help="Keep refreshing every index once loaded, with nobody watching "
                          "(default: on for store workspaces, off for checkouts; or "
                          "server.keep_warm)")
    pui.add_argument("--no-keep-warm", dest="keep_warm", action="store_const", const=False,
                     help="Let an index nobody asked for in 60 s stop refreshing")
    pui.add_argument("--metrics-ended-hours", type=views.positive_int, default=None, metavar="H",
                     help="Keep an ended outer run on /metrics for H hours (default 24; "
                          "or server.metrics_ended_hours)")
    pui.add_argument("--diag-every", type=float, default=None, metavar="SEC",
                     help="Write a diagnostic dump to <data-dir>/diag/ every SEC seconds "
                          "(keeps the last 20; SIGUSR1 writes one on demand)")
    pui.add_argument("--edits", action="store_true", default=False,
                     help="onboarding: also grant the puts server-side edits need")
    pui.add_argument("--format", dest="onboarding_format", default="json",
                     choices=("json", "cloudformation", "terraform"),
                     help="onboarding: output format (default: json)")
    pui.add_argument("--account-id", default=None,
                     help="onboarding: the AWS account the role trusts")
    pui.add_argument("--external-id", default=None,
                     help="onboarding: the org's AssumeRole external id")
    pui.add_argument("--origin", action="append", default=None,
                     help="onboarding: a browser origin allowed by bucket CORS (repeatable)")
    pui.add_argument("--url", dest="diag_url", default=None,
                     help="diag: the server's base URL (e.g. http://host:8265)")
    pui.add_argument("--pid", dest="diag_pid", type=int, default=None,
                     help="diag: signal this vmn-exp ui process (SIGUSR1) to write a dump "
                          "into <data-dir>/diag/")
    pui.add_argument("--wait", dest="diag_wait", type=float, default=30,
                     help="diag --pid: seconds to wait for the dump (default: 30)")
    pui.add_argument("--summarize", dest="diag_summarize", default=None, metavar="FILE",
                     help="diag: print the summary of an existing dump")
    pui.add_argument("-o", "--output", dest="diag_output", default=None, metavar="FILE",
                     help="diag: where to write the dump (default: "
                          "vmn-exp-diag-<ts>.json; --pid: the server's file)")


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


def _ui_run_without_repo(args):
    """An explicit source (--repo, --store, --config) needs no enclosing
    checkout, nor does `ui diag` (a dump of a running server); a bare
    `vmn-exp ui` falls through to serve that checkout."""
    diag = (getattr(args, "ui_args", None) or [None])[0] == "diag"
    if not (diag or args.repo or args.store or args.config):
        return None
    from vmn_exp.ui.cli import handle_ui
    return handle_ui(args)


# ---------------------------------------------------------------------------
# run_without_repo: experiment in from-snapshot mode (moved from entry.py)
# ---------------------------------------------------------------------------

def _exp_run_without_repo(args):
    """Experiment commands that work without a git repo.

    Handles: run under VMN_MODE=disabled, import-mlflow (always git-free),
    from-snapshot mode and the store-only maintenance commands outside a checkout.

    Returns an int exit code if handled, None to fall through to normal dispatch.
    """
    is_experiment = getattr(args, "command", None) in ("experiment", "exp")
    action = getattr(args, "action", None)
    if is_experiment:
        from vmn_exp.cli.exp_parser.ownership import refuse_usage_errors

        usage_error = refuse_usage_errors(args)
        if usage_error:
            return usage_error
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
    if not is_experiment or not (from_snapshot or _store_only_outside_checkout(action)):
        return None

    from vmn_exp.cli.experiment import (
        _get_experiment_storage,
        experiment_add,
        experiment_compact,
        experiment_compare,
        experiment_create,
        experiment_list,
        experiment_prune,
        experiment_push,
        experiment_rewind,
        experiment_run,
        experiment_show,
        experiment_similar,
        experiment_similar_backfill,
        experiment_backfill_children,
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
        "compact": experiment_compact,
        "rewind": experiment_rewind,
        "push": experiment_push,
        "similar": experiment_similar,
        "similar-backfill": experiment_similar_backfill,
        "backfill-children": experiment_backfill_children,
    }

    handler = dispatch.get(action)
    if handler is None:
        VMN_LOGGER.error("Action '%s' requires a git repository", action)
        return 1

    if getattr(args, "writer_id", None):
        os.environ["VMN_WRITER_ID"] = args.writer_id
    params = experiment_storage_params(None, args)
    try:
        storage = _get_experiment_storage(None, params)
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    return handler(None, params, storage, args)


# Maintenance commands that need only a store and an app name: outside a
# checkout they run git-free on the store flags / ``VMN_EXPERIMENT_*``.
_STORE_ONLY_ACTIONS = frozenset({"prune", "backfill-children", "compact", "similar-backfill"})


def _store_only_outside_checkout(action):
    from vmn_exp.core.storage_resolve import try_repo_root

    return action in _STORE_ONLY_ACTIONS and try_repo_root() is None


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


def _snapshot_store_opener(vcs, params):
    from vmn_exp.snapshot.stores import open_configured_snapshot_stores

    return open_configured_snapshot_stores(vcs, params)


def register_dev_version() -> None:
    """The ``vmn.plugins`` entry point: lets ``vmn goto`` restore dev versions
    and ``vmn snapshot`` use the configured experiment store. Idempotent, so
    it survives a registry reset."""
    register_dev_version_loader(_dev_version_loader)
    register_snapshot_store_opener(_snapshot_store_opener)


def register_all() -> None:
    """Every command `vmn-exp` serves. Idempotent."""
    from vmn_exp.cli.experiment import READ_ONLY_ACTIONS as EXP_READ_ONLY_ACTIONS
    from vmn_exp.cli.model_cmd import add_model_parser, model_run_without_repo

    register_dev_version()
    _register(CommandSpec(
        names=("experiment", "exp"),
        add_parser=lambda sp: (
            _add_experiment_parser(sp, "experiment"),
            _add_experiment_parser(sp, "exp"),
        ),
        handle=_handle_experiment,
        access="local",
        read_only_actions=EXP_READ_ONLY_ACTIONS,
        split_after_double_dash=True,
        run_without_repo=_exp_run_without_repo,
    ))
    _register(CommandSpec(
        names=("ui",),
        add_parser=_add_ui_parser,
        handle=_handle_ui,
        access="local",
        run_without_repo=_ui_run_without_repo,
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
    _register_reports()


def _register_reports():
    from vmn_exp.cli import comment, report, settings

    for names, add_parser, run, read_only in (
        (("settings",), settings.add_settings_parser, settings.settings_run_without_repo,
         {"show"}),
        (("report",), report.add_report_parser, report.report_run_without_repo,
         {"list", "show", "export"}),
        (("comment",), comment.add_comment_parser, comment.comment_run_without_repo, set()),
        (("comments",), comment.add_comments_parser, comment.comments_run_without_repo, set()),
    ):
        _register(CommandSpec(
            names=names,
            add_parser=add_parser,
            handle=lambda ctx, run=run: run(ctx.args),
            access="local",
            read_only_actions=frozenset(read_only),
            run_without_repo=run,
        ))
