#!/usr/bin/env python3
"""Read-side access to experiments for the vmn ui API.

Pure, lock-free reads over the same storage layer the CLI uses. Sorting
semantics intentionally mirror ``vmn exp list`` so the web leaderboard and the
CLI always agree.
"""
import os

from version_stamp.cli.experiment import (
    _get_latest_metrics,
    _load_log,
    _metric_sort_descending,
    get_metric_series,
)
from version_stamp.cli.snapshot import _resolve_verstr, get_snapshot_storage
from version_stamp.core.experiment_status import (
    derive_status,
    load_run_state,
    status_fields,
)
from version_stamp.core.experiment_tree import annotate_tree
from version_stamp.ui.readers.config import read_app_conf as _read_app_conf
from version_stamp.ui.readers.versions import version_counts


def experiment_storage(root_path):
    return get_snapshot_storage("local", vmn_root_path=root_path, subdir="experiments")


def metrics_schema(root_path, app_name):
    exp_conf = _read_app_conf(root_path, app_name).get("experiment") or {}
    return exp_conf.get("metrics", {}) or {}


def list_apps(root_path):
    """All vmn apps in a checkout: configured (.vmn/<app>/conf.yml) plus any
    with experiment/snapshot data. Returns rows with experiment counts."""
    vmn_dir = os.path.join(root_path, ".vmn")
    apps = set()
    if os.path.isdir(vmn_dir):
        for dirpath, dirnames, filenames in os.walk(vmn_dir):
            rel = os.path.relpath(dirpath, vmn_dir)
            if rel == "." or rel.split(os.sep)[0].startswith("."):
                continue
            parts = rel.split(os.sep)
            if "branch_conf" in parts:
                continue
            if parts[-1] in ("snapshots", "experiments", "root_snapshots"):
                apps.add(os.sep.join(parts[:-1]).replace(os.sep, "/"))
                dirnames[:] = []
                continue
            if "conf.yml" in filenames:
                apps.add(rel.replace(os.sep, "/"))

    rows = []
    storage = experiment_storage(root_path)
    ver_counts = version_counts(root_path)
    for name in sorted(apps):
        try:
            exp_count = len(storage.list_snapshots(name))
        except Exception:
            exp_count = 0
        rows.append(
            {
                "name": name,
                "experiments": exp_count,
                "versions": ver_counts.get(name, 0),
            }
        )
    return rows


def _last_metric_at(log):
    """Timestamp of the newest ``metrics`` entry (the log is time-ordered)."""
    for entry in reversed(log):
        if entry.get("type") == "metrics":
            return entry.get("timestamp")
    return None


def fetch_experiment_rows(root_path=None, app_name=None, storage=None):
    """Leaderboard rows in storage order (oldest first). The expensive read:
    every experiment's metadata + log.

    Rows are *stable*: they change only when metadata or a log file changes, so
    a cache of them survives the run-state heartbeats. The volatile half lives
    in :func:`fetch_run_states` and the time-derived status in
    :func:`annotate_status`.

    Accepts either ``root_path`` (local checkout) or a pre-built ``storage``
    backend (S3 / remote workspaces).
    """
    if storage is None:
        storage = experiment_storage(root_path)
    rows = []
    for i, meta in enumerate(storage.list_snapshots(app_name)):
        log = _load_log(storage, app_name, meta["verstr"])
        rows.append(
            {
                # 1-based storage index: what `vmn exp show <app> -v @N` resolves.
                # Assigned before any sort so it sticks to the row.
                "idx": i + 1,
                "verstr": meta["verstr"],
                "code_verstr": meta.get("code_verstr", meta["verstr"]),
                "timestamp": meta.get("timestamp"),
                "note": meta.get("note"),
                "branch": meta.get("branch"),
                "base_version": meta.get("base_version"),
                "user_meta": meta.get("user_meta"),
                "metrics": _get_latest_metrics(log),
                "parent": meta.get("parent"),
                "last_metric_at": _last_metric_at(log),
            }
        )
    return rows


def fetch_run_states(root_path=None, app_name=None, storage=None, verstrs=None):
    """``{verstr: raw run state}`` — the cheap, volatile half of a read.

    One tiny file per experiment, rewritten by every heartbeat, which is why it
    is fetched (and cached) apart from the rows.
    """
    if storage is None:
        storage = experiment_storage(root_path)
    if verstrs is None:
        verstrs = [meta["verstr"] for meta in storage.list_snapshots(app_name)]
    return {verstr: load_run_state(storage, app_name, verstr) for verstr in verstrs}


def annotate_status(rows, run_states=None, now=None):
    """Derive each row's status and nesting from its raw run state.

    Time-dependent by design (a stale heartbeat means ``stuck``), so this must
    run on every response and its output must never be cached.

    The status fields are written onto *rows* in place and ``annotate_tree``
    returns the copies callers get back — one copy per response, not three.
    Callers pass rows they just fetched or deserialized, never rows they keep.
    """
    run_states = run_states or {}
    for row in rows:
        row.update(status_fields(run_states.get(row["verstr"]), now=now))
    return annotate_tree(rows)


def rows_with_status(root_path=None, app_name=None, storage=None, now=None):
    """Leaderboard rows plus their derived status, straight from storage."""
    if storage is None:
        storage = experiment_storage(root_path)
    rows = fetch_experiment_rows(app_name=app_name, storage=storage)
    run_states = fetch_run_states(
        app_name=app_name, storage=storage, verstrs=[r["verstr"] for r in rows]
    )
    return annotate_status(rows, run_states, now=now)


def filter_by_status(rows, status=None):
    """Keep rows whose status is in a comma-separated allow list."""
    if not status:
        return rows
    wanted = {s.strip() for s in status.split(",")}
    return [r for r in rows if r["status"] in wanted]


def sort_rows(rows, schema, sort=None, last=None, offset=0, limit=None):
    """Pure ordering over fetched rows — semantics identical to ``vmn exp list``.

    When *limit* is given, returns ``{"rows": [...], "total": N}`` for
    paginated responses.  Without *limit*, returns a plain list (backward
    compatible).
    """
    if last:
        rows = rows[-int(last) :]
    rows = list(rows)

    all_keys = set()
    for r in rows:
        all_keys.update(r["metrics"].keys())

    def _key(metric):
        return lambda r: (
            r["metrics"].get(metric) is None,
            r["metrics"].get(metric, 0),
        )

    if sort and sort in all_keys:
        # Match `vmn exp list`: a metric drives direction only via its own
        # schema entry; a key absent from the schema sorts ascending.
        desc = (
            _metric_sort_descending(schema, sort) if sort in (schema or {}) else False
        )
        rows.sort(key=_key(sort), reverse=desc)
    elif not sort and schema:
        primary = next((k for k, v in schema.items() if v.get("primary")), None)
        if primary and primary in all_keys:
            rows.sort(
                key=_key(primary),
                reverse=_metric_sort_descending(schema, primary),
            )

    if limit is not None:
        total = len(rows)
        rows = rows[offset : offset + limit]
        return {"rows": rows, "total": total}
    return rows


def list_experiments(
    root_path, app_name, sort=None, last=None, offset=0, limit=None, status=None
):
    """Leaderboard rows, ordered exactly like ``vmn exp list``."""
    return sort_rows(
        filter_by_status(rows_with_status(root_path, app_name), status),
        metrics_schema(root_path, app_name),
        sort=sort,
        last=last,
        offset=offset,
        limit=limit,
    )


def _list_artifacts(storage, app_name, verstr):
    art_dir = storage.list_artifact_files(app_name, verstr)
    if not art_dir or not os.path.isdir(art_dir):
        return []
    result = []
    for name in sorted(os.listdir(art_dir)):
        path = os.path.join(art_dir, name)
        if os.path.isfile(path):
            result.append({"name": name, "size": os.path.getsize(path)})
    return result


_DETAIL_STATUS_KEYS = tuple(status_fields(None)) + (
    "parent",
    "children",
    "kind",
    "depth",
    "tree_status",
    "last_metric_at",
)


def _subtree_verstrs(verstr, children_of):
    """*verstr* and everything below it, cycle-safe."""
    seen, stack, out = set(), [verstr], []
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        out.append(current)
        stack.extend(children_of.get(current, []))
    return out


def _status_detail(storage, app_name, verstr, metadata, log):
    """One experiment's status payload, including its place in the run tree.

    Costs one metadata listing plus one run-state read per subtree member — the
    whole workspace is never re-read, and no log is touched: *metadata* and
    *log* come from the caller, which already loaded both.
    """
    nodes = [
        {"verstr": meta["verstr"], "parent": meta.get("parent")}
        for meta in storage.list_snapshots(app_name)
    ]
    children_of = {}
    for node in nodes:
        if node["parent"] and node["parent"] != node["verstr"]:
            children_of.setdefault(node["parent"], []).append(node["verstr"])

    subtree = set(_subtree_verstrs(verstr, children_of))
    run_state = None
    for node in nodes:
        if node["verstr"] not in subtree:
            continue
        state = load_run_state(storage, app_name, node["verstr"])
        node["status"] = derive_status(state)
        if node["verstr"] == verstr:
            run_state = state

    row = next((r for r in annotate_tree(nodes) if r["verstr"] == verstr), {})
    detail = status_fields(run_state)
    detail.update({k: row.get(k) for k in ("children", "kind", "depth", "tree_status")})
    detail["parent"] = metadata.get("parent")
    detail["last_metric_at"] = _last_metric_at(log)
    return {k: detail.get(k) for k in _DETAIL_STATUS_KEYS}


def get_experiment(root_path, app_name, verstr_ref):
    """Full experiment detail; the ref supports @N / prefix / 'latest'."""
    storage = experiment_storage(root_path)
    verstr, err = _resolve_verstr(storage, app_name, verstr_ref, kind="experiment")
    if err:
        return None, err

    metadata, patches = storage.load(app_name, verstr)
    if metadata is None:
        return None, f"Experiment {verstr} not found"

    log = _load_log(storage, app_name, verstr)
    return {
        "metadata": metadata,
        "log": log,
        "metrics": _get_latest_metrics(log),
        "series": get_metric_series(log),
        "artifacts": _list_artifacts(storage, app_name, verstr),
        "status": _status_detail(storage, app_name, verstr, metadata, log),
        "patches": {
            k: bool(patches.get(k))
            for k in ("working_tree", "local_commits", "untracked_files")
        },
    }, None


# ---- Storage-backend functions (S3 / remote workspaces) ----


def list_experiments_from_storage(
    storage, app_name, sort=None, last=None, offset=0, limit=None, status=None
):
    """List experiments using a storage backend directly (for S3/remote workspaces)."""
    schema = {}  # No app conf available for S3 workspaces
    return sort_rows(
        filter_by_status(rows_with_status(app_name=app_name, storage=storage), status),
        schema,
        sort=sort,
        last=last,
        offset=offset,
        limit=limit,
    )


def get_experiment_from_storage(storage, app_name, verstr_ref):
    """Get experiment detail from storage backend directly."""
    verstr, err = _resolve_verstr(storage, app_name, verstr_ref, kind="experiment")
    if err:
        return None, err
    metadata, patches = storage.load(app_name, verstr)
    if metadata is None:
        return None, "Experiment " + verstr + " not found"
    log = _load_log(storage, app_name, verstr)
    return {
        "metadata": metadata,
        "log": log,
        "metrics": _get_latest_metrics(log),
        "series": get_metric_series(log),
        "artifacts": _list_artifacts(storage, app_name, verstr),
        "status": _status_detail(storage, app_name, verstr, metadata, log),
        "patches": {
            k: bool(patches.get(k)) if patches else False
            for k in ("working_tree", "local_commits", "untracked_files")
        },
    }, None


def list_apps_from_storage(storage):
    """List apps from a storage backend (S3). Limited: no version counts or conf."""
    apps = set()
    if hasattr(storage, "_s3") and hasattr(storage, "prefix"):
        try:
            paginator = storage._s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(
                Bucket=storage.bucket, Prefix=storage.prefix + "/", Delimiter="/"
            ):
                for cp in page.get("CommonPrefixes", []):
                    app_name = (
                        cp["Prefix"][len(storage.prefix) + 1 :]
                        .rstrip("/")
                        .replace("_", "/")
                    )
                    apps.add(app_name)
        except Exception:
            pass
    rows = []
    for name in sorted(apps):
        try:
            exp_count = len(storage.list_snapshots(name))
        except Exception:
            exp_count = 0
        rows.append({"name": name, "experiments": exp_count, "versions": 0})
    return rows
