#!/usr/bin/env python3
"""Experiment tracking for reproducible research, built on snapshot infrastructure."""
import os
import shutil
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import List, Optional

import yaml

from version_stamp.cli.experiment_prune import _parse_duration  # noqa: F401
from version_stamp.cli.experiment_prune import experiment_prune as _experiment_prune

# `vmn exp run` lives in its own module; these names stay importable from here.
from version_stamp.cli.experiment_run import (  # noqa: F401
    _METRICS_TAIL_INTERVAL,
    _ingest_metric_records,
    _MetricsTailer,
    _safe_unlink,
    experiment_run,
)
from version_stamp.cli.snapshot import (
    _build_snapshot_metadata,
    _compute_verstr,
    _diff_real_tree,
    _diff_with_external_tool,
    _relative_timestamp,
    _resolve_verstr,
    _restore_with_safety_net,
    _strip_git_dirs,
    gather_create_data,
    get_git_difftool,
    get_snapshot_storage,
)
from version_stamp.core import experiment_index, experiment_writer
from version_stamp.core.experiment_from_snapshot import (
    create_from_snapshot as _experiment_create_from_snapshot,
)
from version_stamp.core.experiment_log import (
    effective_params,
    entry_params,
    latest_metrics,
    load_log,
    metric_series,
    metric_sort_descending,
    sort_by_metric,
)
from version_stamp.core.experiment_status import (
    STUCK,
    derive_status,
    load_run_state,
    status_fields,
)
from version_stamp.core.experiment_tree import (
    annotate_tree,
    children_by_parent,
    subtree_verstrs,
)
from version_stamp.core.experiment_writer import (
    allocate_run_verstr,
    append_to_log,
    attach_parent,
    compute_artifact_info,
    create_log_entry,
    get_repo_lock,  # noqa: F401  (re-exported: cli.entry imports it from here)
    get_writer_id,
    merge_conf_into_params,
    save_artifact,
    save_log,
    save_run_state,
)
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.utils import now_iso

# The log-folding helpers moved to core.experiment_log and the record-shaping
# write primitives to core.experiment_writer, so the ui readers and the
# version_stamp.exp SDK can share them without importing the CLI. These aliases
# keep the old private names importable for existing callers.
_create_entry_params = effective_params
_entry_params = entry_params
_get_latest_metrics = latest_metrics
_load_log = load_log
_metric_sort_descending = metric_sort_descending
get_metric_series = metric_series

_allocate_run_verstr = allocate_run_verstr
_append_to_log = append_to_log
_attach_parent = attach_parent
_compute_artifact_info = compute_artifact_info
_create_log_entry = create_log_entry
_get_writer_id = get_writer_id
_merge_conf_into_params = merge_conf_into_params
_now_iso = now_iso
_save_artifact = save_artifact
_save_log = save_log
_save_run_state = save_run_state


class _WriterIdCacheAlias(ModuleType):
    """Keep ``<this module>._WRITER_ID`` wired to the cache in core.

    The writer-id cache moved to ``core.experiment_writer``, but resetting it by
    assigning to this module's global is how the test suite (and anything else
    that has to re-read ``$VMN_WRITER_ID``) has always done it. A data
    descriptor on the module's type forwards both reads and writes there, so the
    legacy global stays the one true handle on the cache instead of becoming a
    dead copy of it.
    """

    @property
    def _WRITER_ID(self):
        return experiment_writer._WRITER_ID

    @_WRITER_ID.setter
    def _WRITER_ID(self, value):
        experiment_writer._WRITER_ID = value


sys.modules[__name__].__class__ = _WriterIdCacheAlias


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


def _get_experiment_storage(vcs, params):
    experiment_dir = params.get("experiment_dir") or os.environ.get(
        "VMN_EXPERIMENT_DIR"
    )
    vmn_root = experiment_dir or (vcs.vmn_root_path if vcs else None)
    return get_snapshot_storage(
        params.get("backend", "local"),
        vmn_root_path=vmn_root,
        bucket=params.get("bucket"),
        prefix=params.get("prefix", "vmn-experiments"),
        endpoint_url=params.get("endpoint_url"),
        subdir="experiments",
    )


def _resolve_parent(storage, app_name, args):
    """Parent verstr for a new experiment. Returns (parent, error_code).

    ``--parent`` wins over the ``VMN_EXPERIMENT_ID`` exported by an enclosing
    ``vmn exp run``. Both are resolved against storage, so a parent is only ever
    recorded if it exists. An explicit ``--parent`` that cannot be resolved is a
    hard error; a stale env id is dropped with a warning — the outer run may
    simply have been pruned, which is no reason to fail this one.
    """
    ref = getattr(args, "parent", None) if args is not None else None
    explicit = bool(ref)
    ref = ref or os.environ.get("VMN_EXPERIMENT_ID")
    if not ref:
        return None, None

    verstr, err = _resolve_verstr(storage, app_name, ref, kind="experiment")
    if not err:
        return verstr, None
    if explicit:
        VMN_LOGGER.error(err)
        return None, 1
    VMN_LOGGER.warning(f"Ignoring stale VMN_EXPERIMENT_ID '{ref}': {err}")
    return None, None


# ---------------------------------------------------------------------------
# Log entry helpers
# ---------------------------------------------------------------------------


def _parse_metrics(metrics_list):
    """Parse ['loss=0.34', 'acc=0.91'] to {'loss': 0.34, 'acc': 0.91}."""
    result = {}
    for item in metrics_list:
        if "=" not in item:
            VMN_LOGGER.error(f"Invalid --metrics format: {item}. Expected key=value")
            continue
        key, val = item.split("=", 1)
        try:
            result[key.strip()] = float(val.strip())
        except ValueError:
            result[key.strip()] = val.strip()
    return result


def _parse_metric_line(line):
    """Parse one metrics-file line into ``(step_or_None, values)``.

    Grammar: ``[step=N] key=value [key=value ...]``. Returns None for lines
    with no metric values.
    """
    tokens = line.split()
    step = None
    if tokens and tokens[0].startswith("step="):
        try:
            step = int(tokens[0][len("step=") :])
            tokens = tokens[1:]
        except ValueError:
            pass  # "step" used as a metric name; leave tokens intact
    values = _parse_metrics(tokens)
    if not values:
        return None
    return step, values


def _parse_notes_file(path):
    """Read a YAML file and return as dict."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"Notes file must be a YAML mapping, got {type(data).__name__}"
        )
    return data


def _get_metrics_schema(vcs):
    """Read experiment.metrics from conf.yml if present."""
    exp_conf = getattr(vcs, "experiment", None)
    if isinstance(exp_conf, dict):
        return exp_conf.get("metrics", {})
    return {}


def _resolve_experiment_version(storage, vcs, args, default_latest=False):
    """Resolve a version for experiment actions. Returns (verstr, error_msg).

    Delegates to the shared resolver (handles ``--latest``, ``@N``, prefixes and
    candidate listing). When ``default_latest`` is set and no version is given,
    resolves to the most recent experiment.
    """
    versions = getattr(args, "version", None)
    latest = getattr(args, "latest", False)
    ref = versions[0] if versions else None
    if ref is None and not latest and default_latest:
        latest = True
    app_name = _app_name(vcs, args)
    return _resolve_verstr(storage, app_name, ref, latest=latest, kind="experiment")


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


@measure_runtime_decorator
def handle_experiment(vmn_ctx):
    from version_stamp.cli.commands import _get_repo_status, _init_app, handle_init

    vcs = vmn_ctx.vcs
    args = vmn_ctx.args
    action = args.action

    params = {
        "backend": getattr(args, "backend", "local"),
        "bucket": getattr(args, "bucket", None),
        "prefix": getattr(args, "prefix", "vmn-experiments"),
        "endpoint_url": getattr(args, "endpoint_url", None),
    }
    params["experiment_dir"] = getattr(args, "experiment_dir", None)
    params["writer_id"] = getattr(args, "writer_id", None)

    _merge_conf_into_params(vcs, params)
    _export_conf_writer_id(params.get("writer_id"))

    # Auto-init for create/run (zero-setup cold start), unless from_snapshot mode.
    from_snapshot = getattr(args, "from_snapshot", None) or os.environ.get(
        "VMN_SNAPSHOT_METADATA"
    )
    if action in ("create", "run") and not from_snapshot:
        expected_status = {"repo_tracked", "app_tracked"}
        optional_status = {
            "repos_exist_locally",
            "detached",
            "pending",
            "outgoing",
            "version_not_matched",
            "dirty_deps",
            "deps_synced_with_conf",
        }
        # An untracked repo or app is the normal cold-start case here, not a
        # failure: the branch below initializes both. Reporting them as errors
        # first made a successful first run read like a crash.
        status = _get_repo_status(
            vcs,
            expected_status,
            optional_status,
            suppress_errors={"repo_tracked", "app_tracked"},
        )

        if status.error:
            auto_initialized = False
            be = vcs.backend
            vmn_path = os.path.join(vcs.vmn_root_path, ".vmn")
            vmn_init_file = os.path.join(vmn_path, "conf.yml")

            _dirty_ok = {"pending", "outgoing"}

            if "repo_tracked" not in status.state and not be.is_path_tracked(
                vmn_init_file
            ):
                VMN_LOGGER.info("Auto-initializing repository...")
                ret = handle_init(vmn_ctx, extra_optional=_dirty_ok)
                if ret != 0:
                    return 1
                auto_initialized = True

            if "app_tracked" not in status.state and not be.is_path_tracked(
                vcs.app_dir_path
            ):
                # Name the app and the baseline: a typo'd app name becomes a
                # permanent git tag, so creating one must never be silent.
                VMN_LOGGER.info(
                    f"Auto-initializing new vmn app '{vcs.name}' at 0.0.0..."
                )
                err = _init_app(vcs, "0.0.0", extra_optional=_dirty_ok)
                if err:
                    return 1
                auto_initialized = True

            if auto_initialized:
                vcs.update_attrs_from_app_conf_file()
                vcs.initialize_backend_attrs()

    storage = _get_experiment_storage(vcs, params)

    if action == "create":
        return experiment_create(vcs, params, storage, args)
    elif action == "run":
        return experiment_run(
            vcs, params, storage, args, repo_lock=getattr(vmn_ctx, "repo_lock", None)
        )
    elif action == "add":
        return experiment_add(vcs, params, storage, args)
    elif action == "list":
        return experiment_list(vcs, params, storage, args)
    elif action == "show":
        return experiment_show(vcs, params, storage, args)
    elif action == "compare":
        return experiment_compare(vcs, params, storage, args)
    elif action == "diff":
        return experiment_diff(vcs, params, storage, args)
    elif action == "restore":
        return experiment_restore(vcs, params, storage, args)
    elif action == "export":
        return experiment_export(vcs, params, storage, args)
    elif action == "prune":
        return experiment_prune(vcs, params, storage, args)
    else:
        VMN_LOGGER.error(f"Unknown experiment action: {action}")
        return 1


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@measure_runtime_decorator
def experiment_create(vcs, params, storage, args):
    extra = {}
    if getattr(args, "file", None):
        extra.update(_parse_notes_file(args.file))

    from_snapshot = getattr(args, "from_snapshot", None) or os.environ.get(
        "VMN_SNAPSHOT_METADATA"
    )
    app_name = _app_name(vcs, args)
    parent, err = _resolve_parent(storage, app_name, args)
    if err is not None:
        return err

    verstr, err = _experiment_create_core(
        vcs,
        storage,
        note=args.note,
        from_snapshot=from_snapshot,
        extra_create_data=extra or None,
        parent=parent,
    )
    if err is not None:
        return err

    if getattr(args, "metrics", None):
        _append_to_log(
            storage,
            app_name,
            verstr,
            _create_log_entry("metrics", values=_parse_metrics(args.metrics)),
        )

    print(verstr)
    return 0


def _experiment_create_core(
    vcs, storage, note=None, from_snapshot=None, extra_create_data=None, parent=None
):
    """Create the experiment record (snapshot + initial log entry).

    Returns (verstr, error_code). error_code is None on success.
    When from_snapshot is set, reads identity from vmn_metadata.yml (no git needed).
    """
    if from_snapshot:
        app_name = _app_name(vcs)
        return _experiment_create_from_snapshot(
            storage,
            app_name,
            from_snapshot,
            note=note,
            extra_create_data=extra_create_data,
            parent=parent,
        )

    (
        base_version,
        commit_hash,
        patches,
        dirty_states,
        ver_info,
        err,
    ) = gather_create_data(vcs, allow_clean=True)
    if err is not None:
        return None, err

    code_verstr = _compute_verstr(base_version, commit_hash, patches)

    def _record(verstr):
        metadata = _build_snapshot_metadata(
            vcs,
            verstr,
            base_version,
            commit_hash,
            dirty_states,
            patches,
            ver_info,
            note=note,
        )
        metadata["code_verstr"] = code_verstr
        _attach_parent(metadata, parent)
        return metadata, patches

    # Allocation creates the record (see _experiment_create_from_snapshot).
    verstr = _allocate_run_verstr(storage, vcs.name, code_verstr, make_record=_record)

    entry = _create_log_entry("create", note=note)
    if extra_create_data:
        entry.update(extra_create_data)

    _append_to_log(storage, vcs.name, verstr, entry)
    return verstr, None


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


@measure_runtime_decorator
def experiment_add(vcs, params, storage, args):
    verstr, err = _resolve_experiment_version(storage, vcs, args, default_latest=True)
    if err:
        VMN_LOGGER.error(err)
        return 1

    app_name = _app_name(vcs, args)

    if args.metrics:
        entry = _create_log_entry("metrics", values=_parse_metrics(args.metrics))
        _append_to_log(storage, app_name, verstr, entry)
        VMN_LOGGER.info(f"Added metrics to {verstr}")

    if args.note:
        entry = _create_log_entry("note", text=args.note)
        _append_to_log(storage, app_name, verstr, entry)
        VMN_LOGGER.info(f"Added note to {verstr}")

    if args.attach:
        if not os.path.isfile(args.attach):
            VMN_LOGGER.error(f"Artifact file not found: {args.attach}")
            return 1
        info = _compute_artifact_info(args.attach)
        _save_artifact(storage, app_name, verstr, args.attach)
        entry = _create_log_entry("artifact", **info)
        _append_to_log(storage, app_name, verstr, entry)
        VMN_LOGGER.info(f"Attached {info['path']} to {verstr}")

    if args.file:
        notes_data = _parse_notes_file(args.file)
        entry = _create_log_entry("structured", **notes_data)
        _append_to_log(storage, app_name, verstr, entry)
        VMN_LOGGER.info(f"Added structured entry to {verstr}")

    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def _status_tree(storage, app_name, metas, only=None, run_states=None):
    """Annotated nesting/status rows for *metas*, by verstr.

    The tree is built over every meta, so depth and ``tree_status`` stay right
    for any subset. Run states are read only for *only* (a verstr collection)
    and their subtrees; the rest carry no status, which a rollup ignores.
    *run_states* (``{verstr: state}``) supplies them without a read.
    """
    rows = [{"verstr": m["verstr"], "parent": m.get("parent")} for m in metas]
    wanted = None
    if only is not None:
        children_of = children_by_parent(rows)
        wanted = set()
        for verstr in only:
            wanted.update(subtree_verstrs(verstr, children_of))
    for row in rows:
        if wanted is None or row["verstr"] in wanted:
            if run_states is not None:
                state = run_states.get(row["verstr"])
            else:
                state = load_run_state(storage, app_name, row["verstr"])
            row["status"] = derive_status(state)
    return {row["verstr"]: row for row in annotate_tree(rows)}


def _status_token(node):
    """A run's own status, plus its subtree's when the two disagree."""
    status = node["status"]
    tree_status = node.get("tree_status")
    if tree_status and tree_status != status:
        return f"{status}/{tree_status}"
    return status


def _list_rows(index_rows, last):
    """Rows for ``list``: ``idx`` is the storage index ``@N`` resolves, fixed
    before ``--last``/sort/``--top`` touch the order."""
    shown = index_rows[-last:] if last else index_rows
    return [
        {"idx": row["idx"], "meta": row, "metrics": row["metrics"]} for row in shown
    ]


def _metric_columns(schema, rows):
    """Schema-declared metrics first, then the rest alphabetically."""
    keys = set()
    for row in rows:
        keys.update(row["metrics"])
    columns = list(schema or {})
    return columns + sorted(k for k in keys if k not in columns)


def _format_list_row(row, node, columns):
    meta, metrics = row["meta"], row["metrics"]
    note = meta.get("note") or meta.get("create_note") or ""
    metric_str = "  ".join(
        f"{k}={metrics[k]:.4g}" if isinstance(metrics[k], float) else f"{k}={metrics[k]}"
        for k in columns
        if k in metrics
    )
    note_str = f" - {note}" if note else ""
    return (
        f"{'  ' * node['depth']}[{row['idx']}] {meta['verstr']}  "
        f"{_status_token(node)}  ({_relative_timestamp(meta['timestamp'])})  "
        f"{metric_str}{note_str}"
    )


@measure_runtime_decorator
def experiment_list(vcs, params, storage, args):
    app_name = _app_name(vcs, args)
    # Through the experiment index: after the first listing, only the logs and
    # run states that changed since are read again.
    index_rows, run_states = experiment_index.indexed_rows(
        storage, app_name, with_create_note=True
    )
    if not index_rows:
        print(f"No experiments found for {app_name}")
        return 0

    schema = _get_metrics_schema(vcs) if vcs else {}
    rows = _list_rows(index_rows, getattr(args, "last", None))
    if args.sort and not any(args.sort in row["metrics"] for row in rows):
        VMN_LOGGER.warning(f"Sort key '{args.sort}' not found in any experiment")
    rows = sort_by_metric(rows, schema, sort=args.sort)
    if args.top:
        rows = rows[: args.top]

    tree = _status_tree(
        storage,
        app_name,
        index_rows,
        only=[row["meta"]["verstr"] for row in rows],
        run_states=run_states,
    )
    columns = _metric_columns(schema, rows)
    for row in rows:
        print(_format_list_row(row, tree[row["meta"]["verstr"]], columns))
    return 0


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def _subtree_metas(verstr, metas):
    """``verstr``'s row plus every experiment reachable from it via ``parent``.

    Metadata-only, so the caller can read run state for just these — a run tree
    is a handful of rows even when the app has thousands of experiments.
    """
    children_of = {}
    for meta in metas:
        parent = meta.get("parent")
        if parent and parent != meta["verstr"]:
            children_of.setdefault(parent, []).append(meta)
    by_verstr = {m["verstr"]: m for m in metas}

    subtree = []
    seen = set()
    queue = [by_verstr[verstr]] if verstr in by_verstr else []
    while queue:
        meta = queue.pop(0)
        if meta["verstr"] in seen:
            continue
        seen.add(meta["verstr"])
        subtree.append(meta)
        queue.extend(children_of.get(meta["verstr"], []))
    return subtree


def _print_status_block(storage, app_name, verstr, metadata):
    """Derived run status, runner identity and the experiment's nesting."""
    fields = status_fields(load_run_state(storage, app_name, verstr))
    print(f"  Status:    {fields['status']}")
    if fields["exit_code"] is not None:
        print(f"  Exit code: {fields['exit_code']}")
    if fields["duration_sec"] is not None:
        print(f"  Duration:  {fields['duration_sec']}s")
    if fields["pid"]:
        print(f"  Runner:    pid {fields['pid']} on {fields['host']}")
    if fields["status"] == STUCK:
        print(f"  Heartbeat: last seen {_relative_timestamp(fields['heartbeat'])}")

    if metadata.get("parent"):
        print(f"  Parent:    {metadata['parent']}")

    subtree = _subtree_metas(verstr, storage.list_snapshots(app_name))
    if len(subtree) <= 1:
        return  # no children: nothing to roll up
    node = _status_tree(storage, app_name, subtree)[verstr]
    print(f"  Children:  {', '.join(node['children'])}")
    if node["tree_status"] and node["tree_status"] != fields["status"]:
        print(f"  Subtree:   {node['tree_status']}")


@measure_runtime_decorator
def experiment_show(vcs, params, storage, args):
    verstr, err = _resolve_experiment_version(storage, vcs, args, default_latest=True)
    if err:
        VMN_LOGGER.error(err)
        return 1

    app_name = _app_name(vcs, args)
    metadata, patches = storage.load(app_name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Experiment {verstr} not found")
        return 1

    log = load_log(storage, app_name, verstr)

    print(f"Experiment: {verstr}")
    print(f"  Branch:    {metadata.get('branch') or '?'}")
    base_commit = (metadata.get("base_commit") or "?")[:7]
    print(f"  Base:      {metadata.get('base_version') or '?'} ({base_commit})")
    print(f"  Created:   {metadata.get('timestamp', '?')}")
    if metadata.get("note"):
        print(f"  Note:      {metadata['note']}")
    if metadata.get("has_dep_patches"):
        print("  Deps:      patches captured")
    _print_status_block(storage, app_name, verstr, metadata)

    # Patch stats
    for ptype in ("working_tree", "local_commits"):
        if patches.get(ptype):
            lines = patches[ptype].count("\n")
            print(f"  {ptype}: {lines} lines")

    # Metrics from log
    metrics = latest_metrics(log)
    if metrics:
        print("\n  Metrics:")
        for k, v in sorted(metrics.items()):
            print(f"    {k}: {v:.4g}" if isinstance(v, float) else f"    {k}: {v}")

    if log:
        _print_log(log, getattr(args, "full_log", False))
    return 0


SHOW_LOG_TAIL = 50


def _print_log(log, full):
    """The log, newest ``SHOW_LOG_TAIL`` entries unless *full*."""
    print(f"\n  Log ({len(log)} entries):")
    shown = log if full else log[-SHOW_LOG_TAIL:]
    hidden = len(log) - len(shown)
    if hidden:
        print(f"    ({hidden} earlier entries hidden, use --full-log)")
    for entry in shown:
        ts = _relative_timestamp(entry.get("timestamp", ""))
        print(f"    [{ts}] {_describe_log_entry(entry)}")


def _describe_log_entry(entry):
    etype = entry.get("type", "?")
    if etype in ("metrics", "params"):
        vals = entry.get("values" if etype == "metrics" else "params") or {}
        return f"{etype}: " + ", ".join(f"{k}={v}" for k, v in vals.items())
    if etype == "error":
        return f"error: {entry.get('exception', '?')}: {entry.get('message', '')}"
    if etype == "note":
        return f"note: {entry.get('text', '')}"
    if etype == "artifact":
        return f"artifact: {entry.get('path', '?')} ({entry.get('size', 0)} bytes)"
    if etype == "create":
        note = entry.get("note") or ""
        return f"created{': ' + note if note else ''}"
    return etype


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


def _load_metadata(storage, app_name, verstr):
    """An experiment's metadata alone — no patches or untracked tarball."""
    raw = storage.load_file(app_name, verstr, "metadata.yml")
    meta = yaml.safe_load(raw) if raw else None
    return meta if isinstance(meta, dict) else None


def _load_experiment_bundle(storage, vcs, verstr, app_name=None, light=False):
    """Load (meta, patches, log) for an experiment, or None (logging) on error.

    *light* skips the patches (``None`` in their slot): what compare needs.
    """
    app_name = app_name or (_app_name(vcs))
    if light:
        meta, patches = _load_metadata(storage, app_name, verstr), None
    else:
        meta, patches = storage.load(app_name, verstr)
    if meta is None:
        VMN_LOGGER.error(f"Experiment {verstr} not found")
        return None
    return meta, patches, load_log(storage, app_name, verstr)


def _resolve_experiment_bundles(
    storage, vcs, versions, count, cap=None, app_name=None, light=False
):
    """Resolve (meta, patches, log) bundles for compare/diff.

    Uses the given ``-v`` versions (each resolved), or the ``count`` most recent
    when none are given; ``cap`` limits how many are taken. Returns the list, or
    None (logging) on error — at least two experiments are required. *light*
    loads no patches.
    """
    app_name = app_name or (_app_name(vcs))

    if len(versions) == 1:
        VMN_LOGGER.error(
            "Need at least 2 experiments — pass -v <a> -v <b> or none for the latest"
        )
        return None

    if versions:
        verstrs = []
        for v in versions[:cap] if cap else versions:
            resolved, err = _resolve_experiment_version(
                storage, vcs, _VersionStub(version=[v])
            )
            if err:
                VMN_LOGGER.error(err)
                return None
            verstrs.append(resolved)
    else:
        if count < 2:
            VMN_LOGGER.error(f"Need at least 2 experiments, got {count}")
            return None
        snaps = storage.list_snapshots(app_name)
        if len(snaps) < 2:
            VMN_LOGGER.error("Need at least 2 experiments")
            return None
        verstrs = [m["verstr"] for m in snaps[-count:]]

    bundles = []
    for verstr in verstrs:
        bundle = _load_experiment_bundle(
            storage, vcs, verstr, app_name=app_name, light=light
        )
        if bundle is None:
            return None
        bundles.append(bundle)
    return bundles


@measure_runtime_decorator
def experiment_compare(vcs, params, storage, args):
    versions = getattr(args, "version", None) or []
    last = getattr(args, "last", None) or getattr(args, "top", None)
    app_name = _app_name(vcs, args)

    experiments = _resolve_experiment_bundles(
        storage, vcs, versions, count=last or 2, app_name=app_name, light=True
    )
    if experiments is None:
        return 1

    # Metrics comparison table
    schema = _get_metrics_schema(vcs) if vcs else {}
    all_keys = set()
    exp_metrics = []
    for meta, patches, log in experiments:
        m = latest_metrics(log)
        exp_metrics.append(m)
        all_keys.update(m.keys())

    if schema:
        col_order = [k for k in schema if k in all_keys]
        for k in sorted(all_keys):
            if k not in col_order:
                col_order.append(k)
    else:
        col_order = sorted(all_keys)

    if col_order:
        headers = ["metric"] + [e[0]["verstr"][-20:] for e in experiments]
        col_widths = [max(len(h), 12) for h in headers]
        header_line = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
        print(header_line)
        print("-" * len(header_line))

        for key in col_order:
            vals = []
            for m in exp_metrics:
                v = m.get(key)
                if v is None:
                    vals.append("-")
                elif isinstance(v, float):
                    vals.append(f"{v:.4g}")
                else:
                    vals.append(str(v))
            row = [key] + vals
            print("  ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))

    if len(experiments) == 2:
        v1 = experiments[0][0]["verstr"]
        v2 = experiments[1][0]["verstr"]
        print(f"\nRun 'vmn exp diff {app_name} -v {v1} -v {v2}' for a code diff.")

    return 0


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def _fmt_val(v):
    return f"{v:.4g}" if isinstance(v, float) else str(v)


def _print_delta_line(label, d1, d2):
    parts = []
    for k in sorted(set(d1) | set(d2)):
        a, b = d1.get(k), d2.get(k)
        if a != b:
            parts.append(f"{k} {_fmt_val(a)} -> {_fmt_val(b)}")
    if parts:
        print(f"{label}: " + "   ".join(parts))


@measure_runtime_decorator
def experiment_diff(vcs, params, storage, args):
    """Show a real code diff between two experiments, with a params/metrics delta."""
    versions = getattr(args, "version", None) or []
    exps = _resolve_experiment_bundles(storage, vcs, versions, count=2, cap=2)
    if exps is None:
        return 1
    (meta1, patches1, log1), (meta2, patches2, log2) = exps
    v1, v2 = meta1["verstr"], meta2["verstr"]

    print(f"Comparing {v1} -> {v2}\n")
    _print_delta_line("params", effective_params(log1), effective_params(log2))
    _print_delta_line("metrics", latest_metrics(log1), latest_metrics(log2))
    print()

    tool = getattr(args, "tool", None) or get_git_difftool(vcs)
    if tool:
        return _diff_with_external_tool(
            tool, vcs, v1, meta1, patches1, v2, meta2, patches2
        )
    return _diff_real_tree(vcs, v1, meta1, patches1, v2, meta2, patches2)


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


@measure_runtime_decorator
def experiment_restore(vcs, params, storage, args):
    verstr, err = _resolve_experiment_version(storage, vcs, args, default_latest=True)
    if err:
        VMN_LOGGER.error(err)
        return 1

    app_name = _app_name(vcs, args)
    metadata, patches = storage.load(app_name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Experiment {verstr} not found")
        return 1

    return _restore_with_safety_net(vcs, params, metadata, patches)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@measure_runtime_decorator
def experiment_export(vcs, params, storage, args):
    import tarfile
    import tempfile

    verstr, err = _resolve_experiment_version(storage, vcs, args, default_latest=True)
    if err:
        VMN_LOGGER.error(err)
        return 1

    app_name = _app_name(vcs, args)
    metadata, patches = storage.load(app_name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Experiment {verstr} not found")
        return 1

    log = load_log(storage, app_name, verstr)

    safe_verstr = verstr.replace("+", "_plus_")
    output_path = args.output or f"{safe_verstr}.tar.gz"
    is_tarball = output_path.endswith(".tar.gz") or output_path.endswith(".tgz")

    if is_tarball:
        tmpdir = tempfile.mkdtemp(prefix="vmn-exp-export-")
        dest = os.path.join(tmpdir, safe_verstr)
    else:
        tmpdir = None
        dest = output_path

    try:
        from version_stamp.cli.snapshot import _materialize_workdir

        err = _materialize_workdir(vcs, metadata, patches, dest)
        if err:
            return err

        _strip_git_dirs(dest)

        with open(os.path.join(dest, "vmn_experiment.yml"), "w") as f:
            yaml.dump({"metadata": metadata, "log": log}, f, sort_keys=False)

        art_dir = storage.list_artifact_files(app_name, verstr)
        if art_dir and os.path.isdir(art_dir):
            dest_art = os.path.join(dest, "artifacts")
            shutil.copytree(art_dir, dest_art, dirs_exist_ok=True)

        if is_tarball:
            with tarfile.open(output_path, "w:gz") as tar:
                tar.add(dest, arcname=safe_verstr)

        print(output_path)
        return 0
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


@measure_runtime_decorator
def experiment_prune(vcs, params, storage, args):
    return _experiment_prune(vcs, params, storage, args, _app_name(vcs, args))
