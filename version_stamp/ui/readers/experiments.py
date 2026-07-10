#!/usr/bin/env python3
"""Read-side access to experiments for the vmn ui API.

Pure, lock-free reads over the same storage layer the CLI uses. Sorting
semantics intentionally mirror ``vmn exp list`` so the web leaderboard and the
CLI always agree.
"""
import os

import yaml

from version_stamp.cli.experiment import (
    _get_latest_metrics,
    _load_log,
    _metric_sort_descending,
    get_metric_series,
)
from version_stamp.cli.snapshot import _resolve_verstr, get_snapshot_storage


def experiment_storage(root_path):
    return get_snapshot_storage(
        "local", vmn_root_path=root_path, subdir="experiments"
    )


def _read_app_conf(root_path, app_name):
    conf_path = os.path.join(
        root_path, ".vmn", app_name.replace("/", os.sep), "conf.yml"
    )
    try:
        with open(conf_path) as f:
            data = yaml.safe_load(f) or {}
    except OSError:
        return {}
    return data.get("conf", {}) or {}


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
    for name in sorted(apps):
        try:
            exp_count = len(storage.list_snapshots(name))
        except Exception:
            exp_count = 0
        rows.append({"name": name, "experiments": exp_count})
    return rows


def fetch_experiment_rows(root_path, app_name):
    """Leaderboard rows in storage order (oldest first). The expensive read:
    every experiment's metadata + log."""
    storage = experiment_storage(root_path)
    rows = []
    for meta in storage.list_snapshots(app_name):
        log = _load_log(storage, app_name, meta["verstr"])
        rows.append({
            "verstr": meta["verstr"],
            "code_verstr": meta.get("code_verstr", meta["verstr"]),
            "timestamp": meta.get("timestamp"),
            "note": meta.get("note"),
            "branch": meta.get("branch"),
            "base_version": meta.get("base_version"),
            "user_meta": meta.get("user_meta"),
            "metrics": _get_latest_metrics(log),
        })
    return rows


def sort_rows(rows, schema, sort=None, last=None):
    """Pure ordering over fetched rows — semantics identical to ``vmn exp list``."""
    if last:
        rows = rows[-int(last):]
    rows = list(rows)

    all_keys = set()
    for r in rows:
        all_keys.update(r["metrics"].keys())

    def _key(metric):
        return lambda r: (
            r["metrics"].get(metric) is None, r["metrics"].get(metric, 0),
        )

    if sort and sort in all_keys:
        desc = _metric_sort_descending(schema, sort) if schema else False
        rows.sort(key=_key(sort), reverse=desc)
    elif not sort and schema:
        primary = next((k for k, v in schema.items() if v.get("primary")), None)
        if primary and primary in all_keys:
            rows.sort(
                key=_key(primary),
                reverse=_metric_sort_descending(schema, primary),
            )
    return rows


def list_experiments(root_path, app_name, sort=None, last=None):
    """Leaderboard rows, ordered exactly like ``vmn exp list``."""
    return sort_rows(
        fetch_experiment_rows(root_path, app_name),
        metrics_schema(root_path, app_name),
        sort=sort, last=last,
    )


def get_experiment(root_path, app_name, verstr_ref):
    """Full experiment detail; the ref supports @N / prefix / 'latest'."""
    storage = experiment_storage(root_path)
    verstr, err = _resolve_verstr(
        storage, app_name, verstr_ref, kind="experiment"
    )
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
        "artifacts_dir": storage.list_artifact_files(app_name, verstr),
        "patches": {
            k: bool(patches.get(k))
            for k in ("working_tree", "local_commits", "untracked_files")
        },
    }, None
