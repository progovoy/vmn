"""``vmn-exp show``: one run's record, status block, metrics and log.

Helpers that tests patch on :mod:`vmn_exp.cli.experiment`
(``_resolve_experiment_version``, ``load_run_state``) are looked up there at
call time, so such a patch still reaches this module (plan 44 G15). Its text
goes to the given console (plan 44 G16)."""
from vmn_exp.cli import fork
from vmn_exp.cli.duration_text import duration_text
from vmn_exp.cli.list_layout import _lost_text
from vmn_exp.cli.media_view import describe_media_entry, media_lines
from vmn_exp.cli.provenance import format_env_oneliner, format_inputs_lines
from vmn_exp.cli.views import (
    PATCH_MAX_BYTES,
    base_line,
    dumps,
    error_lines,
    event_log,
    format_metric_lines,
    metrics_schema,
    patch_payload,
    patch_stat_lines,
    print_patch,
    show_payload,
    shown_policies,
    split_params,
)
from vmn_exp.core.fold import (
    fold_inputs_dict,
    fold_log,
    fold_metrics,
    fold_values,
    logged_params,
)
from vmn_exp.core.log import load_log, merged_log_view
from vmn_exp.core.metric_entries import is_metric_entry
from vmn_exp.core.metric_summary import SchemaPolicies
from vmn_exp.core.output_log import OUTPUT_LOG_PATH
from vmn_exp.core.refs import point_placement, storage_index, tree_links
from vmn_exp.core.status import STUCK, run_state_observed_at, status_fields
from vmn_exp.core.tree import subtree_status
from version_stamp.api import VMN_LOGGER, measure_runtime_decorator, relative_timestamp


def _subtree(storage, app_name, verstr, metadata, snapshot=None, now=None):
    """``(run_state, tree fields, observed_at)`` of *verstr*: the parent/child
    links come from the experiment index (point reads once it is persisted),
    and run state (with its store write time) is read for the run's subtree
    only — a handful of rows even when the app has thousands of experiments."""
    from vmn_exp.cli import experiment as _exp

    snapshot = point_placement(storage, app_name, snapshot)
    parent_of, children_of = tree_links(snapshot, verstr, metadata.get("parent"))
    observed_at = lambda v: run_state_observed_at(storage, app_name, v)  # noqa: E731
    run_state, tree = subtree_status(
        verstr,
        parent_of,
        lambda v: _exp.load_run_state(storage, app_name, v),
        children_of=children_of,
        observed_at=observed_at,
        row_of=snapshot.row,
        now=now,
    )
    return run_state, tree, observed_at(verstr)


def _print_status_block(storage, app_name, verstr, metadata, out, snapshot=None, now=None):
    """Derived run status (as of *now*), runner identity and the experiment's nesting."""
    run_state, tree, observed_at = _subtree(storage, app_name, verstr, metadata, snapshot, now)
    fields = status_fields(run_state, now=now, observed_at=observed_at)
    out(f"  Status:    {fields['status']}")
    if fields["exit_code"] is not None:
        out(f"  Exit code: {fields['exit_code']}")
    duration = duration_text(fields)
    if duration:
        out(f"  Duration:  {duration}")
    if fields["pid"]:
        out(f"  Runner:    pid {fields['pid']} on {fields['host']}")
    if fields["status"] == STUCK:
        out(f"  Heartbeat: last seen {relative_timestamp(fields['heartbeat'])}")
    error = error_lines((run_state or {}).get("error"))
    if error:
        out(f"  Error:     {error[0]}")
        for line in error[1:]:
            out(f"  {line}")

    if metadata.get("parent"):
        out(f"  Parent:    {metadata['parent']}")

    if not tree["children"]:
        return  # no children: nothing to roll up
    out(f"  Children:  {', '.join(tree['children'])}")
    if tree["tree_status"] and (tree["tree_status"] != fields["status"] or tree["lost_below"]):
        out(f"  Subtree:   {tree['tree_status']}{_lost_text(tree)}")


@measure_runtime_decorator
def _print_output_log(storage, app_name, verstr, out):
    for artifact in storage.list_artifacts(app_name, verstr):
        if artifact["name"] == OUTPUT_LOG_PATH:
            out(f"  Output:    {OUTPUT_LOG_PATH} ({artifact['size']} bytes)")


def _split_fold_params(fold, metrics):
    """:func:`split_params` of *fold*'s *metrics*: ``(logged metrics, params)``."""
    return split_params(metrics, fold_values(fold, "params"), logged_params(fold))


def experiment_show(vcs, params, storage, args, console):
    from vmn_exp.cli import experiment as _exp

    app_name = _exp._app_name(vcs, args)
    snapshot = point_placement(storage, app_name)
    verstr, err = _exp._resolve_experiment_version(
        storage, vcs, args, default_latest=True, snapshot=snapshot
    )
    if err:
        VMN_LOGGER.error(err)
        return 1

    metadata, patches = storage.load(app_name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Experiment {verstr} not found")
        return 1

    out = console.out
    log = load_log(storage, app_name, verstr)
    schema = metrics_schema(vcs, storage, app_name)
    if getattr(args, "json", False):
        return _print_show_json(
            storage, app_name, verstr, metadata, patches, log, args, snapshot, schema, out
        )

    out(f"Experiment: {verstr}")
    out(f"  Branch:    {metadata.get('branch') or '?'}")
    out(f"  {base_line(metadata)}")
    out(f"  Created:   {metadata.get('timestamp', '?')}")
    if metadata.get("note"):
        out(f"  Note:      {metadata['note']}")
    if metadata.get("has_dep_patches"):
        out("  Deps:      patches captured")
    env_summary = metadata.get("env")
    if env_summary:
        out(f"  Env:       {format_env_oneliner(env_summary)}")
    _print_output_log(storage, app_name, verstr, out)
    _print_status_block(storage, app_name, verstr, metadata, out, snapshot)
    fork.print_lineage(metadata, log, out)

    for line in patch_stat_lines(metadata, patches):
        out(f"  {line}")

    # Fold log once for both inputs and metrics
    _fold = fold_log(log)
    inputs = fold_inputs_dict(_fold)
    if inputs:
        out("\n  Inputs:")
        for ln in format_inputs_lines(inputs):
            out(f"  {ln}")

    metrics, summary, overrides = fold_metrics(_fold, schema)
    metrics, run_params = _split_fold_params(_fold, metrics)
    if run_params:
        out("\n  Params:")
        for name, value in sorted(run_params.items()):
            out(f"    {name}: {value}")
    if metrics:
        out("\n  Metrics:")
        shown = shown_policies(metrics, overrides, SchemaPolicies(schema))
        for line in format_metric_lines(metrics, summary, shown):
            out(f"    {line}")

    media = media_lines(log)
    if media:
        out("\n  Media:")
        for line in media:
            out(f"    {line}")

    events = event_log(log)
    if events:
        _print_log(events, getattr(args, "full_log", False), out)
    if getattr(args, "patch", False):
        print_patch(verstr, metadata, patches, getattr(args, "max_bytes", PATCH_MAX_BYTES),
                    out=out, err=console.err)
    return 0


SHOW_LOG_TAIL = 50


def _print_show_json(
    storage, app_name, verstr, metadata, patches, log, args, snapshot, schema, out
):
    run_state, tree, observed_at = _subtree(storage, app_name, verstr, metadata, snapshot)
    idx = storage_index(storage, app_name, verstr, snapshot)
    tail = None if getattr(args, "full_log", False) else SHOW_LOG_TAIL
    payload = show_payload(
        idx, metadata, patches, log, run_state, tree, tail,
        observed_at=observed_at, schema=schema,
    )
    if getattr(args, "patch", False):
        payload["patch"] = patch_payload(
            metadata, patches, getattr(args, "max_bytes", PATCH_MAX_BYTES))
    out(dumps(payload))
    return 0


def _print_log(log, full, out):
    """The log to *out*, newest ``SHOW_LOG_TAIL`` entries unless *full*."""
    out(f"\n  Log ({len(log)} entries):")
    offset = 0 if full else max(len(log) - SHOW_LOG_TAIL, 0)
    shown = merged_log_view(log, offset)["entries"]
    hidden = offset
    if hidden:
        out(f"    ({hidden} earlier entries hidden, use --full-log)")
    for entry in shown:
        ts = relative_timestamp(entry.get("timestamp", ""))
        out(f"    [{ts}] {_describe_log_entry(entry)}")


def _describe_log_entry(entry):
    etype = entry.get("type", "?")
    if is_metric_entry(entry) or etype == "params":
        vals = entry.get("params" if etype == "params" else "values") or {}
        return f"{etype}: " + ", ".join(f"{k}={v}" for k, v in vals.items())
    if etype == "error":
        return f"error: {entry.get('exception', '?')}: {entry.get('message', '')}"
    if etype == "note":
        return f"note: {entry.get('text', '')}"
    if etype == "alert":
        text = entry.get("text")
        head = f"alert [{entry.get('level', 'info')}]: {entry.get('title', '')}"
        return f"{head}: {text}" if text else head
    if etype == "artifact":
        return f"artifact: {entry.get('path', '?')} ({entry.get('size', 0)} bytes)"
    media = describe_media_entry(entry)
    if media:
        return media
    if etype == "create":
        note = entry.get("note") or ""
        return f"created{': ' + note if note else ''}"
    return etype
