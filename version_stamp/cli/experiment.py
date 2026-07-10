#!/usr/bin/env python3
"""Experiment tracking for reproducible research, built on snapshot infrastructure."""
import datetime
import os
import shutil
from dataclasses import dataclass
from typing import List, Optional

import yaml

from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.cli.snapshot import (
    _build_snapshot_metadata,
    _compute_verstr,
    _diff_with_external_tool,
    _diff_real_tree,
    _now_iso,
    _relative_timestamp,
    _resolve_verstr,
    _restore_with_safety_net,
    _sha256_file,
    _strip_git_dirs,
    gather_create_data,
    get_git_difftool,
    get_snapshot_storage,
)


@dataclass
class _VersionStub:
    version: Optional[List[str]] = None
    latest: bool = False


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _get_experiment_storage(vcs, params):
    return get_snapshot_storage(
        params.get("backend", "local"),
        vmn_root_path=vcs.vmn_root_path,
        bucket=params.get("bucket"),
        prefix=params.get("prefix", "vmn-experiments"),
        endpoint_url=params.get("endpoint_url"),
        subdir="experiments",
    )


def _load_log(storage, app_name, verstr):
    """Load experiment log from storage."""
    data = storage.load_file(app_name, verstr, "log.yml")
    if data is None:
        return []
    return yaml.safe_load(data) or []


def _save_log(storage, app_name, verstr, log):
    """Save experiment log to storage."""
    storage.save_file(app_name, verstr, "log.yml", yaml.dump(log, sort_keys=False))


def _append_to_log(storage, app_name, verstr, entry):
    """Append an entry to the experiment log (immutable — never edit existing)."""
    log = _load_log(storage, app_name, verstr)
    log.append(entry)
    _save_log(storage, app_name, verstr, log)


# ---------------------------------------------------------------------------
# Log entry helpers
# ---------------------------------------------------------------------------

def _create_log_entry(entry_type, **kwargs):
    entry = {"timestamp": _now_iso(), "type": entry_type}
    entry.update(kwargs)
    return entry


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
            step = int(tokens[0][len("step="):])
            tokens = tokens[1:]
        except ValueError:
            pass  # "step" used as a metric name; leave tokens intact
    values = _parse_metrics(tokens)
    if not values:
        return None
    return step, values


class _MetricsTailer:
    """Incrementally consume complete lines appended to the metrics file.

    Each ``poll()`` returns the newly completed lines as parsed
    ``(step, values)`` tuples; a trailing partial line stays buffered until
    its newline arrives.
    """

    def __init__(self, path):
        self._path = path
        self._offset = 0

    def poll(self):
        try:
            with open(self._path) as f:
                f.seek(self._offset)
                chunk = f.read()
        except OSError:
            return []
        if not chunk:
            return []

        complete, sep, _partial = chunk.rpartition("\n")
        if not sep:
            return []  # no complete line yet
        self._offset += len(complete) + 1

        records = []
        for line in complete.split("\n"):
            line = line.strip()
            if not line:
                continue
            parsed = _parse_metric_line(line)
            if parsed:
                records.append(parsed)
        return records


def get_metric_series(log):
    """Fold a log into per-metric point lists for charting.

    Returns ``{metric: [{"step": N|None, "ts": iso, "value": v}, ...]}`` in
    log order.
    """
    series = {}
    for entry in log:
        if entry.get("type") != "metrics":
            continue
        step = entry.get("step")
        ts = entry.get("timestamp")
        for key, value in (entry.get("values") or {}).items():
            series.setdefault(key, []).append(
                {"step": step, "ts": ts, "value": value}
            )
    return series


def _parse_notes_file(path):
    """Read a YAML file and return as dict."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Notes file must be a YAML mapping, got {type(data).__name__}")
    return data


def _compute_artifact_info(path):
    """Compute sha256 and size for an artifact file."""
    return {
        "path": os.path.basename(path),
        "size": os.path.getsize(path),
        "sha256": _sha256_file(path),
    }


def _save_artifact(storage, app_name, verstr, src_path):
    """Copy an artifact file into the experiment directory."""
    storage.save_artifact_file(app_name, verstr, src_path)


def _get_metrics_schema(vcs):
    """Read experiment.metrics from conf.yml if present."""
    exp_conf = getattr(vcs, "experiment", None)
    if isinstance(exp_conf, dict):
        return exp_conf.get("metrics", {})
    return {}


def _metric_sort_descending(schema, key):
    """Whether metric ``key`` sorts best-first as descending (higher is better).

    Driven by ``goal: min|max`` in the metrics schema (``max`` = higher-is-better
    = descending). Unspecified metrics default to higher-is-better.
    """
    entry = (schema or {}).get(key, {}) or {}
    goal = entry.get("goal")
    if goal is None:
        return True
    if goal not in ("min", "max"):
        VMN_LOGGER.warning(f"Invalid goal '{goal}' for metric '{key}'; using 'max'")
        goal = "max"
    return goal == "max"


def _get_latest_metrics(log):
    """Scan log entries and return the latest value for each metric."""
    metrics = {}
    for entry in log:
        if entry.get("type") == "metrics" and "values" in entry:
            metrics.update(entry["values"])
        elif entry.get("type") == "create" and "params" in entry:
            for k, v in entry["params"].items():
                try:
                    metrics[k] = float(v)
                except (ValueError, TypeError):
                    pass
    return metrics


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
    return _resolve_verstr(storage, vcs.name, ref, latest=latest, kind="experiment")


def _parse_duration(duration_str):
    """Parse '30d', '2w', '24h' to timedelta."""
    s = duration_str.strip().lower()
    if s.endswith("d"):
        return datetime.timedelta(days=int(s[:-1]))
    if s.endswith("w"):
        return datetime.timedelta(weeks=int(s[:-1]))
    if s.endswith("h"):
        return datetime.timedelta(hours=int(s[:-1]))
    raise ValueError(f"Invalid duration: {duration_str}. Use Nd, Nw, or Nh.")


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

@measure_runtime_decorator
def handle_experiment(vmn_ctx):
    from version_stamp.cli.commands import _get_repo_status, handle_init, _init_app

    vcs = vmn_ctx.vcs
    args = vmn_ctx.args
    action = args.action

    params = {
        "backend": getattr(args, "backend", "local"),
        "bucket": getattr(args, "bucket", None),
        "prefix": getattr(args, "prefix", "vmn-experiments"),
        "endpoint_url": getattr(args, "endpoint_url", None),
    }

    # Read experiment storage config from app conf, CLI overrides
    exp_conf = getattr(vcs, "experiment", None) or {}
    storage_conf = exp_conf.get("storage", {}) or getattr(vcs, "snapshot_storage", None) or {}
    for key in ("bucket", "backend", "prefix", "endpoint_url"):
        if not params.get(key) or params[key] in ("local", "vmn-experiments"):
            conf_val = storage_conf.get(key)
            if conf_val:
                params[key] = conf_val

    # Auto-init for create/run (zero-setup cold start).
    if action in ("create", "run"):
        expected_status = {"repo_tracked", "app_tracked"}
        optional_status = {
            "repos_exist_locally", "detached", "pending", "outgoing",
            "version_not_matched", "dirty_deps", "deps_synced_with_conf",
        }
        status = _get_repo_status(vcs, expected_status, optional_status)

        if status.error:
            auto_initialized = False
            be = vcs.backend
            vmn_path = os.path.join(vcs.vmn_root_path, ".vmn")
            vmn_init_file = os.path.join(vmn_path, "conf.yml")

            _dirty_ok = {"pending", "outgoing"}

            if "repo_tracked" not in status.state and not be.is_path_tracked(vmn_init_file):
                VMN_LOGGER.info("Auto-initializing repository...")
                ret = handle_init(vmn_ctx, extra_optional=_dirty_ok)
                if ret != 0:
                    return 1
                auto_initialized = True

            if "app_tracked" not in status.state and not be.is_path_tracked(vcs.app_dir_path):
                VMN_LOGGER.info(f"Auto-initializing app '{vcs.name}'...")
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
        return experiment_run(vcs, params, storage, args)
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

def _allocate_run_verstr(storage, app_name, code_verstr):
    """Return the verstr for a new experiment run over ``code_verstr``.

    Content-addressed code state maps many runs to one code verstr; each new run
    over an existing state gets a ``.N`` suffix so runs never overwrite one
    another (e.g. same code, different seed).
    """
    runs = []
    for meta in storage.list_snapshots(app_name):
        v = meta.get("verstr", "")
        if v == code_verstr:
            runs.append(1)
        elif v.startswith(code_verstr + ".r"):
            suffix = v[len(code_verstr) + 2:]
            if suffix.isdigit():
                runs.append(int(suffix))
    if not runs:
        return code_verstr
    return f"{code_verstr}.r{max(runs) + 1}"


@measure_runtime_decorator
def experiment_create(vcs, params, storage, args):
    verstr, err = _experiment_create_core(vcs, storage, note=args.note)
    if err is not None:
        return err

    if args.file or args.metrics:
        log = _load_log(storage, vcs.name, verstr)
        if args.file:
            notes_data = _parse_notes_file(args.file)
            for k, v in notes_data.items():
                log[0][k] = v
        if args.metrics:
            log.append(_create_log_entry("metrics", values=_parse_metrics(args.metrics)))
        _save_log(storage, vcs.name, verstr, log)

    print(verstr)
    return 0


def _experiment_create_core(vcs, storage, note=None):
    """Create the experiment record (snapshot + initial log entry).

    Returns (verstr, error_code). error_code is None on success. Works on a clean
    or dirty tree; repeat runs over identical code state get a run suffix.
    """
    base_version, commit_hash, patches, dirty_states, ver_info, err = \
        gather_create_data(vcs, allow_clean=True)
    if err is not None:
        return None, err

    code_verstr = _compute_verstr(base_version, commit_hash, patches)
    verstr = _allocate_run_verstr(storage, vcs.name, code_verstr)

    metadata = _build_snapshot_metadata(
        vcs, verstr, base_version, commit_hash, dirty_states, patches,
        ver_info, note=note,
    )
    metadata["code_verstr"] = code_verstr

    storage.save(vcs.name, verstr, metadata, patches)
    _save_log(storage, vcs.name, verstr, [_create_log_entry("create", note=note)])
    return verstr, None


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@measure_runtime_decorator
def experiment_run(vcs, params, storage, args):
    """Create an experiment, run a command, and record its outcome + metrics.

    The child inherits stdio (output streams live) and these env vars:
    VMN_EXPERIMENT_ID, VMN_APP_NAME, VMN_METRICS_FILE. Any ``key=value`` lines the
    child appends to VMN_METRICS_FILE are recorded as a metrics entry. Returns the
    child's exit code.
    """
    import subprocess
    import tempfile
    import time

    run_cmd = getattr(args, "run_cmd", None)
    if not run_cmd:
        VMN_LOGGER.error(
            "No command to run. Usage: vmn exp run <app> -- <command> [args...]"
        )
        return 1

    verstr, err = _experiment_create_core(vcs, storage, note=args.note)
    if err is not None:
        return err

    if args.file:
        log = _load_log(storage, vcs.name, verstr)
        notes_data = _parse_notes_file(args.file)
        for key in ("params", "hypothesis", "tags"):
            if key in notes_data:
                log[0][key] = notes_data[key]
        _save_log(storage, vcs.name, verstr, log)

    fd, metrics_path = tempfile.mkstemp(prefix="vmn-metrics-")
    os.close(fd)
    env = dict(os.environ)
    env["VMN_EXPERIMENT_ID"] = verstr
    env["VMN_APP_NAME"] = vcs.name
    env["VMN_METRICS_FILE"] = metrics_path

    VMN_LOGGER.info(f"Experiment {verstr}: running {' '.join(run_cmd)}")
    tailer = _MetricsTailer(metrics_path)
    start = time.monotonic()
    try:
        proc = subprocess.Popen(run_cmd, env=env, cwd=vcs.vmn_root_path)
    except FileNotFoundError:
        VMN_LOGGER.error(f"Command not found: {run_cmd[0]}")
        _safe_unlink(metrics_path)
        return 1

    # Tail the metrics file for the whole run so the log is live during
    # training; a final drain after exit catches the tail.
    while proc.poll() is None:
        _ingest_metric_records(storage, vcs.name, verstr, tailer.poll())
        time.sleep(_METRICS_TAIL_INTERVAL)
    exit_code = proc.returncode
    duration = round(time.monotonic() - start, 3)

    _ingest_metric_records(storage, vcs.name, verstr, tailer.poll())
    _safe_unlink(metrics_path)

    _append_to_log(storage, vcs.name, verstr, _create_log_entry(
        "run", command=run_cmd, exit_code=exit_code, duration_sec=duration,
    ))

    VMN_LOGGER.info(f"Experiment {verstr}: exited {exit_code} in {duration}s")
    print(verstr)
    return exit_code


_METRICS_TAIL_INTERVAL = 0.5  # seconds between metrics-file polls during a run


def _ingest_metric_records(storage, app_name, verstr, records):
    """Append one metrics log entry per parsed (step, values) record."""
    if not records:
        return
    log = _load_log(storage, app_name, verstr)
    for step, values in records:
        entry = _create_log_entry("metrics", values=values)
        if step is not None:
            entry["step"] = step
        log.append(entry)
    _save_log(storage, app_name, verstr, log)


def _safe_unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

@measure_runtime_decorator
def experiment_add(vcs, params, storage, args):
    verstr, err = _resolve_experiment_version(storage, vcs, args, default_latest=True)
    if err:
        VMN_LOGGER.error(err)
        return 1

    if args.metrics:
        entry = _create_log_entry("metrics", values=_parse_metrics(args.metrics))
        _append_to_log(storage, vcs.name, verstr, entry)
        VMN_LOGGER.info(f"Added metrics to {verstr}")

    if args.note:
        entry = _create_log_entry("note", text=args.note)
        _append_to_log(storage, vcs.name, verstr, entry)
        VMN_LOGGER.info(f"Added note to {verstr}")

    if args.attach:
        if not os.path.isfile(args.attach):
            VMN_LOGGER.error(f"Artifact file not found: {args.attach}")
            return 1
        info = _compute_artifact_info(args.attach)
        _save_artifact(storage, vcs.name, verstr, args.attach)
        entry = _create_log_entry("artifact", **info)
        _append_to_log(storage, vcs.name, verstr, entry)
        VMN_LOGGER.info(f"Attached {info['path']} to {verstr}")

    if args.file:
        notes_data = _parse_notes_file(args.file)
        entry = _create_log_entry("structured", **notes_data)
        _append_to_log(storage, vcs.name, verstr, entry)
        VMN_LOGGER.info(f"Added structured entry to {verstr}")

    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@measure_runtime_decorator
def experiment_list(vcs, params, storage, args):
    experiments = storage.list_snapshots(vcs.name)
    if not experiments:
        print(f"No experiments found for {vcs.name}")
        return 0

    last = getattr(args, "last", None)
    if last:
        experiments = experiments[-last:]

    schema = _get_metrics_schema(vcs)

    rows = []
    all_metric_keys = set()
    for meta in experiments:
        log = _load_log(storage, vcs.name, meta["verstr"])
        metrics = _get_latest_metrics(log)
        all_metric_keys.update(metrics.keys())
        rows.append((meta, metrics, log))

    # Determine column order from schema, then auto-discovered
    if schema:
        col_order = list(schema.keys())
        for k in sorted(all_metric_keys):
            if k not in col_order:
                col_order.append(k)
    else:
        col_order = sorted(all_metric_keys)

    # Sort
    sort_key = args.sort
    if sort_key and sort_key not in all_metric_keys:
        VMN_LOGGER.warning(f"Sort key '{sort_key}' not found in any experiment")
    if sort_key and sort_key in all_metric_keys:
        sort_desc = False
        if schema and sort_key in schema:
            sort_desc = _metric_sort_descending(schema, sort_key)
        rows.sort(
            key=lambda r: (r[1].get(sort_key) is None, r[1].get(sort_key, 0)),
            reverse=sort_desc,
        )
    elif not sort_key and schema:
        primary = next((k for k, v in schema.items() if v.get("primary")), None)
        if primary and primary in all_metric_keys:
            sort_desc = _metric_sort_descending(schema, primary)
            rows.sort(
                key=lambda r: (r[1].get(primary) is None, r[1].get(primary, 0)),
                reverse=sort_desc,
            )

    if args.top:
        rows = rows[:args.top]

    # Print table
    for idx, (meta, metrics, log) in enumerate(rows, 1):
        ts = _relative_timestamp(meta["timestamp"])
        note = meta.get("note") or ""
        create_entry = next((e for e in log if e.get("type") == "create"), None)
        if not note and create_entry:
            note = create_entry.get("note") or ""

        metric_parts = []
        for k in col_order:
            if k in metrics:
                v = metrics[k]
                metric_parts.append(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}")

        metric_str = "  ".join(metric_parts)
        note_str = f" - {note}" if note else ""
        print(f"[{idx}] {meta['verstr']}  ({ts})  {metric_str}{note_str}")

    return 0


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

@measure_runtime_decorator
def experiment_show(vcs, params, storage, args):
    verstr, err = _resolve_experiment_version(storage, vcs, args, default_latest=True)
    if err:
        VMN_LOGGER.error(err)
        return 1

    metadata, patches = storage.load(vcs.name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Experiment {verstr} not found")
        return 1

    log = _load_log(storage, vcs.name, verstr)

    print(f"Experiment: {verstr}")
    print(f"  Branch:    {metadata.get('branch', '?')}")
    print(f"  Base:      {metadata.get('base_version', '?')} ({metadata.get('base_commit', '?')[:7]})")
    print(f"  Created:   {metadata.get('timestamp', '?')}")
    if metadata.get("note"):
        print(f"  Note:      {metadata['note']}")
    if metadata.get("has_dep_patches"):
        print(f"  Deps:      patches captured")

    # Patch stats
    for ptype in ("working_tree", "local_commits"):
        if patches.get(ptype):
            lines = patches[ptype].count("\n")
            print(f"  {ptype}: {lines} lines")

    # Metrics from log
    metrics = _get_latest_metrics(log)
    if metrics:
        print("\n  Metrics:")
        for k, v in sorted(metrics.items()):
            print(f"    {k}: {v:.4g}" if isinstance(v, float) else f"    {k}: {v}")

    # Log entries
    if log:
        print(f"\n  Log ({len(log)} entries):")
        for entry in log:
            ts = _relative_timestamp(entry.get("timestamp", ""))
            etype = entry.get("type", "?")
            if etype == "metrics":
                vals = entry.get("values", {})
                val_str = ", ".join(f"{k}={v}" for k, v in vals.items())
                print(f"    [{ts}] metrics: {val_str}")
            elif etype == "note":
                print(f"    [{ts}] note: {entry.get('text', '')}")
            elif etype == "artifact":
                print(f"    [{ts}] artifact: {entry.get('path', '?')} ({entry.get('size', 0)} bytes)")
            elif etype == "create":
                note = entry.get("note") or ""
                print(f"    [{ts}] created{': ' + note if note else ''}")
            else:
                print(f"    [{ts}] {etype}")

    return 0


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

def _load_experiment_bundle(storage, vcs, verstr):
    """Load (meta, patches, log) for an experiment, or None (logging) on error."""
    meta, patches = storage.load(vcs.name, verstr)
    if meta is None:
        VMN_LOGGER.error(f"Experiment {verstr} not found")
        return None
    return meta, patches, _load_log(storage, vcs.name, verstr)


def _resolve_experiment_bundles(storage, vcs, versions, count, cap=None):
    """Resolve (meta, patches, log) bundles for compare/diff.

    Uses the given ``-v`` versions (each resolved), or the ``count`` most recent
    when none are given; ``cap`` limits how many are taken. Returns the list, or
    None (logging) on error — at least two experiments are required.
    """
    if len(versions) == 1:
        VMN_LOGGER.error(
            "Need at least 2 experiments — pass -v <a> -v <b> or none for the latest"
        )
        return None

    if versions:
        verstrs = []
        for v in versions[:cap] if cap else versions:
            resolved, err = _resolve_experiment_version(storage, vcs, _VersionStub(version=[v]))
            if err:
                VMN_LOGGER.error(err)
                return None
            verstrs.append(resolved)
    else:
        if count < 2:
            VMN_LOGGER.error(f"Need at least 2 experiments, got {count}")
            return None
        snaps = storage.list_snapshots(vcs.name)
        if len(snaps) < 2:
            VMN_LOGGER.error("Need at least 2 experiments")
            return None
        verstrs = [m["verstr"] for m in snaps[-count:]]

    bundles = []
    for verstr in verstrs:
        bundle = _load_experiment_bundle(storage, vcs, verstr)
        if bundle is None:
            return None
        bundles.append(bundle)
    return bundles


@measure_runtime_decorator
def experiment_compare(vcs, params, storage, args):
    versions = getattr(args, "version", None) or []
    last = getattr(args, "last", None) or getattr(args, "top", None)

    experiments = _resolve_experiment_bundles(storage, vcs, versions, count=last or 2)
    if experiments is None:
        return 1

    # Metrics comparison table
    schema = _get_metrics_schema(vcs)
    all_keys = set()
    exp_metrics = []
    for meta, patches, log in experiments:
        m = _get_latest_metrics(log)
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
        print(f"\nRun 'vmn exp diff {vcs.name} -v {v1} -v {v2}' for a code diff.")

    return 0


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

def _create_entry_params(log):
    create = next((e for e in log if e.get("type") == "create"), {})
    return create.get("params", {}) or {}


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
    _print_delta_line("params", _create_entry_params(log1), _create_entry_params(log2))
    _print_delta_line("metrics", _get_latest_metrics(log1), _get_latest_metrics(log2))
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

    metadata, patches = storage.load(vcs.name, verstr)
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

    metadata, patches = storage.load(vcs.name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Experiment {verstr} not found")
        return 1

    log = _load_log(storage, vcs.name, verstr)

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

        art_dir = storage.list_artifact_files(vcs.name, verstr)
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
    experiments = storage.list_snapshots(vcs.name)
    if not experiments:
        print("No experiments to prune")
        return 0

    keep = getattr(args, "keep", None)
    older_than = getattr(args, "older_than", None)

    to_delete = []
    if keep is not None:
        if keep == 0:
            to_delete = list(experiments)
        elif len(experiments) <= keep:
            print(f"Only {len(experiments)} experiments, nothing to prune (--keep {keep})")
            return 0
        else:
            to_delete = experiments[:-keep]
    elif older_than is not None:
        try:
            delta = _parse_duration(older_than)
        except ValueError as e:
            VMN_LOGGER.error(str(e))
            return 1
        cutoff = datetime.datetime.now(datetime.timezone.utc) - delta
        for meta in experiments:
            try:
                ts = datetime.datetime.fromisoformat(
                    meta["timestamp"].replace("Z", "+00:00")
                )
                if ts < cutoff:
                    to_delete.append(meta)
            except Exception:
                pass
    else:
        VMN_LOGGER.error("Specify --keep N or --older-than Xd")
        return 1

    if not to_delete:
        print("Nothing to prune")
        return 0

    deleted = 0
    for meta in to_delete:
        storage.delete(vcs.name, meta["verstr"])
        deleted += 1

    kept = len(experiments) - deleted
    print(f"Pruned {deleted} experiments, kept {kept}")
    return 0
