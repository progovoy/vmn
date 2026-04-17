#!/usr/bin/env python3
"""Experiment tracking for reproducible research, built on snapshot infrastructure."""
import datetime
import hashlib
import os
import shutil

import yaml

from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.cli.snapshot import (
    CachedSnapshotStorage,
    _apply_snapshot_patches,
    _compute_verstr,
    _diff_builtin,
    _diff_with_external_tool,
    _generate_dep_patches,
    _generate_patches,
    _relative_timestamp,
    _strip_git_dirs,
    get_snapshot_storage,
    snapshot_export,
)


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
    if isinstance(storage, CachedSnapshotStorage):
        s = storage._local
    else:
        s = storage
    if hasattr(s, "_snapshot_dir"):
        log_path = os.path.join(s._snapshot_dir(app_name, verstr), "log.yml")
        if os.path.isfile(log_path):
            with open(log_path) as f:
                return yaml.safe_load(f) or []
    return []


def _save_log(storage, app_name, verstr, log):
    """Save experiment log to storage."""
    if isinstance(storage, CachedSnapshotStorage):
        s = storage._local
    else:
        s = storage
    if hasattr(s, "_snapshot_dir"):
        log_path = os.path.join(s._snapshot_dir(app_name, verstr), "log.yml")
        with open(log_path, "w") as f:
            yaml.dump(log, f, sort_keys=False)


def _append_to_log(storage, app_name, verstr, entry):
    """Append an entry to the experiment log (immutable — never edit existing)."""
    log = _load_log(storage, app_name, verstr)
    log.append(entry)
    _save_log(storage, app_name, verstr, log)


# ---------------------------------------------------------------------------
# Log entry helpers
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


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


def _parse_notes_file(path):
    """Read a YAML file and return as dict."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Notes file must be a YAML mapping, got {type(data).__name__}")
    return data


def _compute_artifact_info(path):
    """Compute sha256 and size for an artifact file."""
    size = os.path.getsize(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return {
        "path": os.path.basename(path),
        "size": size,
        "sha256": h.hexdigest(),
    }


def _save_artifact(storage, app_name, verstr, src_path):
    """Copy an artifact file into the experiment directory."""
    if isinstance(storage, CachedSnapshotStorage):
        s = storage._local
    else:
        s = storage
    if hasattr(s, "_snapshot_dir"):
        art_dir = os.path.join(s._snapshot_dir(app_name, verstr), "artifacts")
        os.makedirs(art_dir, exist_ok=True)
        shutil.copy2(src_path, os.path.join(art_dir, os.path.basename(src_path)))


def _get_metrics_schema(vcs):
    """Read experiment.metrics from conf.yml if present."""
    exp_conf = getattr(vcs, "experiment", None)
    if isinstance(exp_conf, dict):
        return exp_conf.get("metrics", {})
    return {}


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


def _resolve_experiment_version(storage, vcs, args):
    """Resolve version for experiment actions. Returns (verstr, error_msg)."""
    versions = getattr(args, "version", None)
    latest = getattr(args, "latest", None)

    if latest is not None:
        snaps = storage.list_snapshots(vcs.name)
        if not snaps:
            return None, f"No experiments found for {vcs.name}"
        return snaps[-1]["verstr"], None

    if versions and len(versions) == 1:
        verstr = versions[0]
        if storage.exists(vcs.name, verstr):
            return verstr, None
        snaps = storage.list_snapshots(vcs.name)
        matches = [m for m in snaps if m["verstr"].startswith(verstr)]
        if len(matches) == 1:
            return matches[0]["verstr"], None
        if len(matches) > 1:
            return None, f"Ambiguous prefix '{verstr}'"
        return None, f"Experiment '{verstr}' not found"

    return None, None


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

    # Auto-init for create action
    if action == "create":
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

            if "repo_tracked" not in status.state and not be.is_path_tracked(vmn_init_file):
                VMN_LOGGER.info("Auto-initializing repository...")
                ret = handle_init(vmn_ctx)
                if ret != 0:
                    return 1
                auto_initialized = True

            if "app_tracked" not in status.state and not be.is_path_tracked(vcs.app_dir_path):
                VMN_LOGGER.info(f"Auto-initializing app '{vcs.name}'...")
                err = _init_app(vcs, "0.0.0")
                if err:
                    return 1
                auto_initialized = True

            if auto_initialized:
                vcs.update_attrs_from_app_conf_file()
                vcs.initialize_backend_attrs()

    storage = _get_experiment_storage(vcs, params)

    if action == "create":
        return experiment_create(vcs, params, storage, args)
    elif action == "add":
        return experiment_add(vcs, params, storage, args)
    elif action == "list":
        return experiment_list(vcs, params, storage, args)
    elif action == "show":
        return experiment_show(vcs, params, storage, args)
    elif action == "compare":
        return experiment_compare(vcs, params, storage, args)
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
    from version_stamp.cli.commands import _get_repo_status
    from version_stamp.cli.output import get_dirty_states

    expected_status = {"repo_tracked", "app_tracked"}
    optional_status = {
        "repos_exist_locally", "detached", "pending", "outgoing",
        "version_not_matched", "dirty_deps", "deps_synced_with_conf",
    }
    status = _get_repo_status(vcs, expected_status, optional_status)
    if status.error:
        VMN_LOGGER.error("Failed to get repo status for experiment create")
        return 1

    ver_infos = vcs.ver_infos_from_repo
    tag_name = vcs.selected_tag
    if tag_name not in ver_infos:
        VMN_LOGGER.error(f"No stamped version found for '{vcs.name}'")
        return 1

    ver_info = ver_infos[tag_name]["ver_info"]
    if vcs.root_context:
        base_version = str(ver_info["stamping"]["root_app"]["version"])
    else:
        base_version = ver_info["stamping"]["app"]["_version"]

    be = vcs.backend
    commit_hash = be.changeset()

    patches = _generate_patches(be)
    dep_patches = _generate_dep_patches(vcs)
    if dep_patches:
        patches["deps"] = dep_patches

    verstr = _compute_verstr(base_version, commit_hash, patches)

    try:
        remote_url = be.remote()
    except Exception:
        remote_url = None

    dirty_states = list(get_dirty_states(optional_status, status))

    metadata = {
        "verstr": verstr,
        "base_version": base_version,
        "base_commit": commit_hash,
        "branch": be.active_branch,
        "remote": remote_url,
        "timestamp": _now_iso(),
        "note": args.note,
        "app_name": vcs.name,
        "dirty_states": dirty_states,
        "has_working_tree_patch": "working_tree" in patches,
        "has_local_commits_patch": "local_commits" in patches,
        "has_untracked_files": "untracked_files" in patches,
        "has_dep_patches": bool(dep_patches),
    }

    changesets = ver_info["stamping"]["app"].get("changesets", {})
    if changesets:
        metadata["changesets"] = changesets

    storage.save(vcs.name, verstr, metadata, patches)

    # Build first log entry
    log_entry = _create_log_entry("create", note=args.note)

    if args.file:
        notes_data = _parse_notes_file(args.file)
        if "params" in notes_data:
            log_entry["params"] = notes_data["params"]
        if "hypothesis" in notes_data:
            log_entry["hypothesis"] = notes_data["hypothesis"]
        if "tags" in notes_data:
            log_entry["tags"] = notes_data["tags"]
        for k, v in notes_data.items():
            if k not in ("params", "hypothesis", "tags"):
                log_entry[k] = v

    if args.metrics:
        log_entry["params"] = _parse_metrics(args.metrics)

    _save_log(storage, vcs.name, verstr, [log_entry])

    print(verstr)
    return 0


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

@measure_runtime_decorator
def experiment_add(vcs, params, storage, args):
    verstr, err = _resolve_experiment_version(storage, vcs, args)
    if err:
        VMN_LOGGER.error(err)
        return 1
    if not verstr:
        # Default to latest
        snaps = storage.list_snapshots(vcs.name)
        if not snaps:
            VMN_LOGGER.error(f"No experiments found for {vcs.name}")
            return 1
        verstr = snaps[-1]["verstr"]

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
    if sort_key and sort_key in all_metric_keys:
        sort_desc = False
        if schema and sort_key in schema:
            sort_desc = schema[sort_key].get("sort", "asc") == "desc"
        rows.sort(
            key=lambda r: (r[1].get(sort_key) is None, r[1].get(sort_key, 0)),
            reverse=sort_desc,
        )
    elif not sort_key and schema:
        primary = next((k for k, v in schema.items() if v.get("primary")), None)
        if primary and primary in all_metric_keys:
            sort_desc = schema[primary].get("sort", "asc") == "desc"
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
    verstr, err = _resolve_experiment_version(storage, vcs, args)
    if err:
        VMN_LOGGER.error(err)
        return 1
    if not verstr:
        snaps = storage.list_snapshots(vcs.name)
        if not snaps:
            VMN_LOGGER.error(f"No experiments found for {vcs.name}")
            return 1
        verstr = snaps[-1]["verstr"]

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

@measure_runtime_decorator
def experiment_compare(vcs, params, storage, args):
    versions = getattr(args, "version", None) or []
    latest_n = getattr(args, "latest", None)

    experiments = []
    if latest_n:
        snaps = storage.list_snapshots(vcs.name)
        n = latest_n if latest_n > 1 else 2
        if len(snaps) < 2:
            VMN_LOGGER.error("Need at least 2 experiments to compare")
            return 1
        for meta in snaps[-n:]:
            _, patches = storage.load(vcs.name, meta["verstr"])
            log = _load_log(storage, vcs.name, meta["verstr"])
            experiments.append((meta, patches, log))
    elif len(versions) >= 2:
        for v in versions:
            stub = type("A", (), {"version": [v], "latest": None})()
            resolved, err = _resolve_experiment_version(storage, vcs, stub)
            if err:
                VMN_LOGGER.error(err)
                return 1
            meta, patches = storage.load(vcs.name, resolved)
            if meta is None:
                VMN_LOGGER.error(f"Experiment {v} not found")
                return 1
            log = _load_log(storage, vcs.name, resolved)
            experiments.append((meta, patches, log))
    else:
        VMN_LOGGER.error("Specify -v <v1> -v <v2> or --latest N")
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

    # Code diff
    tool = getattr(args, "tool", None) or os.environ.get("VMN_DIFFTOOL")
    if len(experiments) == 2:
        meta1, patches1, _ = experiments[0]
        meta2, patches2, _ = experiments[1]
        if tool:
            print()
            return _diff_with_external_tool(
                tool, vcs,
                meta1["verstr"], meta1, patches1,
                meta2["verstr"], meta2, patches2,
            )
        else:
            print()
            return _diff_builtin(
                meta1["verstr"], meta1, patches1,
                meta2["verstr"], meta2, patches2,
            )

    return 0


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

@measure_runtime_decorator
def experiment_restore(vcs, params, storage, args):
    verstr, err = _resolve_experiment_version(storage, vcs, args)
    if err:
        VMN_LOGGER.error(err)
        return 1
    if not verstr:
        snaps = storage.list_snapshots(vcs.name)
        if not snaps:
            VMN_LOGGER.error(f"No experiments found for {vcs.name}")
            return 1
        verstr = snaps[-1]["verstr"]

    metadata, patches = storage.load(vcs.name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Experiment {verstr} not found")
        return 1

    return _apply_snapshot_patches(vcs, params, metadata, patches)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@measure_runtime_decorator
def experiment_export(vcs, params, storage, args):
    import tarfile
    import tempfile

    verstr, err = _resolve_experiment_version(storage, vcs, args)
    if err:
        VMN_LOGGER.error(err)
        return 1
    if not verstr:
        snaps = storage.list_snapshots(vcs.name)
        if not snaps:
            VMN_LOGGER.error(f"No experiments found for {vcs.name}")
            return 1
        verstr = snaps[-1]["verstr"]

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

        if isinstance(storage, CachedSnapshotStorage) and hasattr(storage._local, "_snapshot_dir"):
            art_dir = os.path.join(storage._local._snapshot_dir(vcs.name, verstr), "artifacts")
            if os.path.isdir(art_dir):
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
        if len(experiments) <= keep:
            print(f"Only {len(experiments)} experiments, nothing to prune (--keep {keep})")
            return 0
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
        if hasattr(storage, "delete"):
            storage.delete(vcs.name, meta["verstr"])
            deleted += 1

    kept = len(experiments) - deleted
    print(f"Pruned {deleted} experiments, kept {kept}")
    return 0
