#!/usr/bin/env python3
"""The programmatic read side of ``vmn exp``: query runs from Python.

::

    from version_stamp.exp.reader import get_run, list_runs

    for run in list_runs(status="failed"):
        print(run["verstr"], run["metrics"])

Rows carry exactly what the dashboard shows for a run: its metadata, the latest
value of every metric, the derived status fields and its place in the run tree.

Status is *derived* on every call — a run whose heartbeat went stale reports
``stuck`` the next time it is read, never the ``running`` it last claimed. So
nothing here is cached; callers that need caching cache the files, not the rows.

Depends on ``version_stamp.core`` and the snapshot/CLI helpers only, never on
``version_stamp.ui``, so the experiment feature can be lifted out later.
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
from version_stamp.core.experiment_status import (
    derive_status,
    load_run_state,
    status_fields,
)
from version_stamp.core.experiment_tree import annotate_tree
from version_stamp.core.utils import resolve_root_path
from version_stamp.exp import _resolve_app_name

EXPERIMENTS_DIR = "experiments"


# ---------------------------------------------------------------------------
# Resolving what the caller left out
# ---------------------------------------------------------------------------


def _experiment_storage(root_path):
    """The checkout's local experiments. An S3 workspace passes its own storage."""
    return get_snapshot_storage(
        "local", vmn_root_path=root_path, subdir=EXPERIMENTS_DIR
    )


def _apps_with_experiments(root_path):
    """Every app under ``.vmn`` that has an experiments directory."""
    vmn_dir = os.path.join(root_path, ".vmn")
    apps = []
    for dirpath, dirnames, _ in os.walk(vmn_dir):
        if os.path.basename(dirpath) != EXPERIMENTS_DIR:
            continue
        dirnames[:] = []  # experiment dirs, nothing to look for inside
        rel = os.path.relpath(os.path.dirname(dirpath), vmn_dir)
        apps.append(rel.replace(os.sep, "/"))
    return sorted(apps)


def _resolve(app_name, storage):
    """Fill in the app name and storage from the current repo.

    Returns ``(app_name, storage, root_path)``; *root_path* is None when the
    caller supplied both, since then no checkout is involved (an S3 workspace,
    say) and there is no conf.yml to read.
    """
    root_path = None if (app_name and storage) else resolve_root_path()
    app_name = _resolve_app_name(app_name, lambda: _apps_with_experiments(root_path))
    return app_name, storage or _experiment_storage(root_path), root_path


def _metrics_schema(root_path, app_name):
    """``experiment.metrics`` from the app's conf.yml — drives sort direction.

    The app conf only, like the ui reads it; branch confs are not consulted.
    """
    if root_path is None:
        return {}
    path = os.path.join(root_path, ".vmn", app_name.replace("/", os.sep), "conf.yml")
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}
    conf = data.get("conf") or {}
    return (conf.get("experiment") or {}).get("metrics") or {}


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _last_metric_at(log):
    """Timestamp of the newest ``metrics`` entry (the log is time-ordered)."""
    for entry in reversed(log):
        if entry.get("type") == "metrics":
            return entry.get("timestamp")
    return None


def _row(idx, meta, log):
    return {
        # 1-based storage index: what `vmn exp show <app> -v @N` resolves.
        "idx": idx,
        "verstr": meta["verstr"],
        "code_verstr": meta.get("code_verstr", meta["verstr"]),
        "timestamp": meta.get("timestamp"),
        "note": meta.get("note"),
        "branch": meta.get("branch"),
        "base_version": meta.get("base_version"),
        "user_meta": meta.get("user_meta"),
        "parent": meta.get("parent"),
        "metrics": _get_latest_metrics(log),
        "last_metric_at": _last_metric_at(log),
    }


def _all_rows(app_name, storage):
    """Every run of an app, status-annotated, in storage order (oldest first).

    Reads every run's log and run state, which is what listing needs; asking
    about a single run goes through :func:`_subtree_row` instead.
    """
    rows = []
    for idx, meta in enumerate(storage.list_snapshots(app_name), 1):
        verstr = meta["verstr"]
        row = _row(idx, meta, _load_log(storage, app_name, verstr))
        row.update(status_fields(load_run_state(storage, app_name, verstr)))
        rows.append(row)
    return annotate_tree(rows)


def _filter_by_status(rows, status):
    """Keep rows whose status is in *status* — a list or a comma-separated string."""
    if not status:
        return rows
    names = status.split(",") if isinstance(status, str) else status
    wanted = {s.strip() for s in names}
    return [r for r in rows if r["status"] in wanted]


def _sort_by_metric(rows, schema, sort=None):
    """Order rows like ``vmn exp list``: by *sort*, else by the primary metric.

    A metric's direction comes from its own schema entry; a metric absent from
    the schema sorts ascending.
    """
    keys = set()
    for row in rows:
        keys.update(row["metrics"])

    metric = sort or next((k for k, v in schema.items() if v.get("primary")), None)
    if not metric or metric not in keys:
        return rows

    descending = metric in schema and _metric_sort_descending(schema, metric)
    return sorted(
        rows,
        key=lambda r: (r["metrics"].get(metric) is None, r["metrics"].get(metric, 0)),
        reverse=descending,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_runs(app_name=None, storage=None, sort=None, last=None, status=None):
    """Runs of an app, oldest first unless *sort* or a primary metric reorders.

    Args:
        app_name: the vmn app; inferred from the current repo when omitted.
        storage: a snapshot storage backend; the local checkout's when omitted.
            Passing one together with *app_name* skips the checkout entirely, so
            there is no conf.yml to take sort direction from.
        sort: a metric name to order by.
        last: keep only the *last* runs (applied before sorting).
        status: keep only these statuses — a list or a comma-separated string.
    """
    app_name, storage, root_path = _resolve(app_name, storage)
    rows = _filter_by_status(_all_rows(app_name, storage), status)
    if last:
        rows = rows[-int(last) :]
    return _sort_by_metric(rows, _metrics_schema(root_path, app_name), sort=sort)


def _artifacts(storage, app_name, verstr):
    art_dir = storage.list_artifact_files(app_name, verstr)
    if not art_dir or not os.path.isdir(art_dir):
        return []
    return [
        {"name": name, "size": os.path.getsize(os.path.join(art_dir, name))}
        for name in sorted(os.listdir(art_dir))
        if os.path.isfile(os.path.join(art_dir, name))
    ]


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


def _subtree_row(app_name, storage, verstr):
    """The row for one run, costing the run's subtree rather than the workspace.

    A metadata-only listing gives the parent/child edges and the row's index; run
    states are then read for the subtree alone, which is all ``tree_status`` can
    depend on. No log is read here — the caller loads the one it needs.
    """
    nodes, target = [], None
    for idx, meta in enumerate(storage.list_snapshots(app_name), 1):
        node = {"idx": idx, "meta": meta, "verstr": meta["verstr"]}
        node["parent"] = meta.get("parent")
        nodes.append(node)
        if node["verstr"] == verstr:
            target = node
    if target is None:
        return None, None

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

    tree = next(r for r in annotate_tree(nodes) if r["verstr"] == verstr)
    status = status_fields(run_state)
    status.update({k: tree[k] for k in ("children", "kind", "depth", "tree_status")})
    return target, status


def get_run(app_name=None, ref="latest", storage=None):
    """One run: a :func:`list_runs` row plus its ``log``, ``series`` and ``artifacts``.

    *ref* takes whatever the CLI takes — a full verstr, a unique prefix, ``@N``
    or ``latest``. Raises ValueError when it resolves to nothing.
    """
    app_name, storage, _ = _resolve(app_name, storage)
    verstr, err = _resolve_verstr(storage, app_name, ref or "latest", kind="experiment")
    if err:
        raise ValueError(err)

    target, status = _subtree_row(app_name, storage, verstr)
    if target is None:
        raise ValueError(f"Experiment '{verstr}' not found for {app_name}")

    log = _load_log(storage, app_name, verstr)
    row = _row(target["idx"], target["meta"], log)
    row.update(status)
    row["log"] = log
    row["series"] = get_metric_series(log)
    row["artifacts"] = _artifacts(storage, app_name, verstr)
    return row
