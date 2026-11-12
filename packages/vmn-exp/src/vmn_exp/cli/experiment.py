#!/usr/bin/env python3
"""Experiment tracking for reproducible research, built on snapshot infrastructure.

This module holds the shared argument and storage helpers and the
``vmn-exp`` action dispatch; each command lives in its own module (plan 44
G15) and is imported back here, where tests and other modules find it."""
import os
from dataclasses import dataclass
from typing import List, Optional

import yaml

from vmn_exp.cli.manage import experiment_manage

# `vmn-exp run` lives in its own module; these names stay importable from here.
from vmn_exp.cli.run import (  # noqa: F401
    _MetricsTailer,
    _parse_metric_line,
    _parse_metrics,
    experiment_run,
)
from vmn_exp.cli.exp_parser.actions import MANAGE_ACTIONS
from vmn_exp.cli.exp_parser.ownership import refuse_usage_errors
from vmn_exp.cli.intent_arg import read_intent
from vmn_exp.cli.snapshot_arg import from_snapshot_metadata
from vmn_exp.core.storage_resolve import _get_experiment_storage, store_uri
from vmn_exp.storage.store_marker import require_store
from vmn_exp.gitmode.coldstart import cold_start_notice, init_tracking
import vmn_exp.core.writer as experiment_writer
from vmn_exp.core.refs import resolve_experiment, resolve_parent
from vmn_exp.core.writer import append_to_log, merge_conf_into_params
from version_stamp.api import VMN_LOGGER, measure_runtime_decorator, now_iso
from vmn_exp.cli.inputs_arg import parse_input_arg
from vmn_exp.core.inputs import create_input_entry

# Names tests and other modules import, or patch, on this module.
from vmn_exp.core.from_snapshot import (  # noqa: F401
    create_from_snapshot as _experiment_create_from_snapshot,
)
from vmn_exp.core.status import load_run_state  # noqa: F401
from version_stamp.api import export_tree, relative_timestamp  # noqa: F401

# The commands, one module each.
from vmn_exp.cli.compare_view import (  # noqa: F401
    _resolve_experiment_bundles,
    experiment_compare,
    experiment_diff,
)
from vmn_exp.cli.experiment_create import (  # noqa: F401
    _experiment_create_core,
    experiment_add,
    experiment_create,
)
from vmn_exp.cli.experiment_export import (  # noqa: F401
    experiment_export,
    experiment_prune,
    experiment_restore,
)
from vmn_exp.cli.experiment_show import (  # noqa: F401
    _describe_log_entry,
    _print_status_block,
    experiment_show,
)
from vmn_exp.cli.list_layout import (  # noqa: F401
    _format_list_row,
    _list_rows,
    _status_token,
    experiment_list,
)


def _append_inputs(storage, app_name, verstr, inputs_list):
    """Append one input log entry per ``--input`` argument."""
    if not inputs_list:
        return
    ts = now_iso()
    for raw in inputs_list:
        name, uri, digest = parse_input_arg(raw)
        entry = create_input_entry(uri, name=name, digest=digest, ts=ts)
        append_to_log(storage, app_name, verstr, entry)


@dataclass
class _VersionStub:
    version: Optional[List[str]] = None
    latest: bool = False


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------


def _app_name(vcs, args=None):
    """Derive app name from vcs or CLI args (safe when vcs is None)."""
    if vcs is not None:
        return vcs.name
    return getattr(args, "name", None) if args is not None else None


def _other_configured_apps(vcs):
    """Names of vmn apps already configured in this repo, other than *vcs.name*.

    Mirrors the ``.vmn/<app>/conf.yml`` layout the ui reader's ``list_apps``
    walks: an app is "configured" once it has its own conf.yml under ``.vmn/``.
    """
    vmn_dir = os.path.join(vcs.vmn_root_path, ".vmn")
    if not os.path.isdir(vmn_dir):
        return []

    apps = set()
    for dirpath, dirnames, filenames in os.walk(vmn_dir):
        rel = os.path.relpath(dirpath, vmn_dir)
        if rel == ".":
            continue
        parts = rel.split(os.sep)
        if parts[0].startswith(".") or "branch_conf" in parts:
            dirnames[:] = []
            continue
        if "conf.yml" in filenames:
            apps.add("/".join(parts))

    apps.discard(vcs.name)
    return sorted(apps)


def _closest_app_names(name, candidates, limit=3):
    """A simple, dependency-free "did you mean" hint: substring match first,
    falling back to difflib's stdlib fuzzy matcher, else the full list."""
    substring_hits = [c for c in candidates if name in c or c in name]
    if substring_hits:
        return substring_hits[:limit]

    import difflib

    close = difflib.get_close_matches(name, candidates, n=limit, cutoff=0.5)
    return close or candidates[:limit]


def _new_app_guard_error(app_name, other_apps):
    hints = _closest_app_names(app_name, other_apps)
    return (
        f"App '{app_name}' does not exist, and this repo already has "
        f"{'an app' if len(other_apps) == 1 else 'apps'} "
        f"({', '.join(other_apps)}). Did you mean: {', '.join(hints)}? "
        f"If '{app_name}' is genuinely a new app, re-run with --new-app."
    )


def _resolve_parent(storage, app_name, args, env):
    """``--parent``, else the enclosing run's ``VMN_EXPERIMENT_ID`` in *env*:
    ``(parent, err)``."""
    return resolve_parent(
        storage,
        app_name,
        getattr(args, "parent", None),
        env.get("VMN_EXPERIMENT_ID"),
    )


# ---------------------------------------------------------------------------
# Log entry helpers
# ---------------------------------------------------------------------------


def _parse_notes_file(path):
    """Read a YAML file and return as dict."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"Notes file must be a YAML mapping, got {type(data).__name__}"
        )
    return data


def _resolve_experiment_version(
    storage, vcs, args, default_latest=False, snapshot=None
):
    """Resolve a version for experiment actions. Returns (verstr, error_msg).

    Delegates to the shared resolver (handles ``--latest``, ``@N``, prefixes and
    candidate listing). When ``default_latest`` is set and no version is given,
    resolves to the most recent experiment. *snapshot* is an index snapshot
    the caller already holds.
    """
    versions = getattr(args, "version", None)
    latest = getattr(args, "latest", False)
    ref = versions[0] if versions else None
    if ref is None and not latest and default_latest:
        latest = True
    app_name = _app_name(vcs, args)
    return resolve_experiment(storage, app_name, ref, latest=latest, snapshot=snapshot)


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------


def _export_conf_writer_id(writer_id):
    """Make a conf ``experiment.storage.writer_id`` act like ``--writer-id``.

    ``$VMN_WRITER_ID`` (and ``--writer-id``, which sets it) still wins.
    """
    if not writer_id or os.environ.get(experiment_writer.WRITER_ID_ENV):
        return
    os.environ[experiment_writer.WRITER_ID_ENV] = writer_id
    experiment_writer._WRITER_ID = None  # re-read on the next log append


def experiment_storage_params(vcs, args, env):
    """The storage params of *args*, conf.yml's filling the gaps."""
    params = {
        "store": getattr(args, "store", None),
        "bucket": getattr(args, "bucket", None),
        "prefix": getattr(args, "prefix", None),
        "endpoint_url": getattr(args, "endpoint_url", None),
        "experiment_dir": getattr(args, "experiment_dir", None),
        "writer_id": getattr(args, "writer_id", None),
    }
    merge_conf_into_params(vcs, params, env)
    _export_conf_writer_id(params.get("writer_id"))
    return params


def auto_init(vmn_ctx):
    """Initialize the repo and the app when either is untracked (a zero-setup
    cold start). Returns 1 on failure, None otherwise."""
    from version_stamp.api import init_needed

    vcs = vmn_ctx.vcs
    repo_missing, app_missing = init_needed(vcs)

    # A brand-new app name in a repo that already has other apps is far more
    # likely a typo than a deliberate new app, and unlike `vmn show`/`vmn goto`
    # this path commits and tags (and pushes, with a remote). Refuse unless the
    # repo is genuinely uninitialized (no other app could exist yet) or the
    # user opted in with --new-app.
    if app_missing and not repo_missing and not getattr(vmn_ctx.args, "new_app", False):
        other_apps = _other_configured_apps(vcs)
        if other_apps:
            VMN_LOGGER.error(_new_app_guard_error(vcs.name, other_apps))
            return 1

    if not (repo_missing or app_missing):
        return None
    return _announced_init(vcs, repo_missing, app_missing) or None


def _announced_init(vcs, repo_missing, app_missing):
    """Init, pushing only when there is a remote to push to (plan 17 F6: a CI
    checkout's first run publishes its baseline), and say what it did."""
    from version_stamp.api import auto_init_if_needed

    remote = vcs.backend.selected_remote
    remote_name = remote.name if remote is not None else None
    notice = cold_start_notice(
        vcs.name, repo_missing, app_missing, pushed=remote is not None, remote=remote_name,
    )
    if remote is not None:
        VMN_LOGGER.info(notice)
    err, _ = init_tracking(vcs, auto_init_if_needed, push=remote is not None)
    if remote is None and not err:
        VMN_LOGGER.info(notice)
    return err


# Actions that never write the store (they take no repo lock either).
READ_ONLY_ACTIONS = frozenset({"list", "show", "compare", "diff", "export", "import-mlflow",
                               "watch", "lineage", "importance",
                               "export-metrics", "similar"})


def _open_checked_storage(vcs, params, action, args=None, *, clock, env):
    """The experiment storage; a read-only action refuses a configured store
    that doesn't exist (a mistyped URI) instead of listing nothing."""
    writer = action not in READ_ONLY_ACTIONS or getattr(args, "compact", False)
    storage = _get_experiment_storage(vcs, params, writer=writer, clock=clock, env=env)
    if not writer:
        require_store(storage, store_uri(params))
    return storage


@measure_runtime_decorator
def handle_experiment(vmn_ctx, io):
    vcs = vmn_ctx.vcs
    args = vmn_ctx.args
    action = args.action
    usage_error = refuse_usage_errors(args)
    if usage_error:
        return usage_error

    params = experiment_storage_params(vcs, args, io.env)

    # Auto-init for create/run (zero-setup cold start), unless from_snapshot mode.
    if action in ("create", "run") and not from_snapshot_metadata(args, io.env):
        # A bad intent must fail before the cold start stamps a baseline.
        if read_intent(args)[1]:
            return 1
        err = auto_init(vmn_ctx)
        if err:
            return err

    try:
        storage = _open_checked_storage(vcs, params, action, args, clock=io.clock, env=io.env)
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return 1

    if action in MANAGE_ACTIONS:
        return experiment_manage(_app_name(vcs, args), storage, args)
    if action == "create":
        return experiment_create(vcs, params, storage, args,
                                 repo_lock=getattr(vmn_ctx, "repo_lock", None), clock=io.clock,
                                 env=io.env)
    elif action == "run":
        return experiment_run(
            vcs, params, storage, args, repo_lock=getattr(vmn_ctx, "repo_lock", None), io=io
        )
    elif action == "rerun":
        from vmn_exp.cli.rerun import experiment_rerun

        return experiment_rerun(
            vcs, params, storage, args, repo_lock=getattr(vmn_ctx, "repo_lock", None), io=io
        )
    elif action == "add":
        return experiment_add(vcs, params, storage, args, io)
    elif action == "list":
        return experiment_list(vcs, params, storage, args, io.console, io.clock)
    elif action == "show":
        return experiment_show(vcs, params, storage, args, io.console, io.clock)
    elif action == "compare":
        return experiment_compare(vcs, params, storage, args, io.console)
    elif action == "diff":
        return experiment_diff(vcs, params, storage, args, io.console)
    elif action == "restore":
        return experiment_restore(vcs, params, storage, args, io.clock, io.env)
    elif action == "export":
        return experiment_export(vcs, params, storage, args, io.console)
    elif action == "prune":
        return experiment_prune(vcs, params, storage, args, io.clock)
    elif action == "importance":
        from vmn_exp.cli.importance import experiment_importance

        return experiment_importance(storage, _app_name(vcs, args), args)
    elif action == "watch":
        from vmn_exp.cli.watch import experiment_watch

        return experiment_watch(vcs, storage, _app_name(vcs, args), args, io.clock, io.env)
    elif action == "rewind":
        return experiment_rewind(vcs, params, storage, args, io.clock)
    elif action == "export-metrics":
        from vmn_exp.cli.export_metrics import experiment_export_metrics

        return experiment_export_metrics(storage, _app_name(vcs, args), args)
    elif action == "compact":
        return experiment_compact(vcs, params, storage, args, io.clock)
    elif action == "push":
        return experiment_push(vcs, params, storage, args, io.clock, io.env)
    elif action == "lineage":
        from vmn_exp.cli.lineage import experiment_lineage

        return experiment_lineage(storage, _app_name(vcs, args), args)
    elif action == "similar":
        return experiment_similar(vcs, params, storage, args, io.clock)
    elif action == "similar-backfill":
        return experiment_similar_backfill(vcs, params, storage, args, io.clock)
    elif action == "backfill-children":
        return experiment_backfill_children(vcs, params, storage, args)
    else:
        VMN_LOGGER.error(f"Unknown experiment action: {action}")
        return 1



def experiment_rewind(vcs, params, storage, args, clock):
    from vmn_exp.cli.rewind import experiment_rewind as rewind

    return rewind(storage, _app_name(vcs, args), args, clock)


def experiment_similar(vcs, params, storage, args, clock):
    from vmn_exp.cli.similar import experiment_similar as similar

    return similar(vcs, storage, _app_name(vcs, args), args, clock)


def experiment_similar_backfill(vcs, params, storage, args, clock):
    from vmn_exp.cli.similar_backfill import experiment_similar_backfill as backfill

    return backfill(storage, _app_name(vcs, args), args, clock)


def experiment_backfill_children(vcs, params, storage, args):
    from vmn_exp.cli.backfill_children import experiment_backfill_children as backfill

    return backfill(storage, _app_name(vcs, args), args)


def experiment_compact(vcs, params, storage, args, clock):
    from vmn_exp.cli.compact import experiment_compact as compact

    return compact(storage, _app_name(vcs, args), args, clock)


def experiment_push(vcs, params, storage, args, clock, env):
    from vmn_exp.cli.push import experiment_push as push

    return push(vcs, params, _app_name(vcs, args), args, clock, env)
