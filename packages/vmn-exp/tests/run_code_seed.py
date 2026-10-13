"""Seed run records on disk as `vmn-exp run` leaves them, for the run-page
code/failure API tests (``/patch``, ``/baselines``, the K4 detail fields)."""
import json
import os
import uuid

import yaml

API = "/api/v1/workspaces/main/apps"


def record_dir(app_layout, verstr):
    path = os.path.join(
        app_layout.repo_path, ".vmn", "store", "runs", app_layout.app_name, verstr
    )
    os.makedirs(path, exist_ok=True)
    return path


def finished_state(exit_code, command=("python", "train.py")):
    return {
        "state": "finished",
        "command": list(command),
        "pid": 1,
        "host": "box",
        "started_at": "2026-09-21T12:00:00Z",
        "heartbeat": "2026-09-21T12:01:00Z",
        "heartbeat_interval_sec": 30,
        "exit_code": exit_code,
        "finished_at": "2026-09-21T12:01:00Z",
        "duration_sec": 60,
    }


def seed_run(
    app_layout, verstr, minute, run_state=None, branch="master", parent=None,
    entries=(), name=None, **metadata
):
    """A record created at 12:*minute*; *entries* are its log lines."""
    path = record_dir(app_layout, verstr)
    meta = {
        "format_version": 2,
        "verstr": verstr,
        "code_verstr": verstr,
        "timestamp": f"2026-09-21T12:{minute:02d}:00Z",
        "branch": branch,
        "base_version": "0.0.1",
        "has_working_tree_patch": False,
        "has_local_commits_patch": False,
        "has_untracked_files": False,
        **metadata,
    }
    if parent:
        meta["parent"] = parent
    if name:
        meta["name"] = name
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f, sort_keys=True)
    if run_state is not None:
        with open(os.path.join(path, "run_state.yml"), "w") as f:
            yaml.dump(run_state, f, sort_keys=False)
    log = os.path.join(path, "log", "w0.jsonl")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "a") as f:
        for entry in entries:
            f.write(json.dumps(dict({"timestamp": meta["timestamp"]}, **entry)) + "\n")
    return path


def write_output(app_layout, verstr, data):
    path = os.path.join(record_dir(app_layout, verstr), "outputs", "output.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def metrics(values, step=None):
    entry = {"type": "metrics", "values": values}
    if step is not None:
        entry["step"] = step
    return entry


def client(app_layout):
    from fastapi.testclient import TestClient
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, f"ui_data_{uuid.uuid4().hex}"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager))


def run_url(app_layout, verstr, tail=""):
    return f"{API}/{app_layout.app_name}/experiments/{verstr}{tail}"
