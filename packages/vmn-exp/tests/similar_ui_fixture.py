"""Workspaces of raw run records for the similar-runs UI routes' tests.

``ws1`` holds two apps: ``app1`` (a target run, its twin, an unrelated run, a
rerun of the target (its code and params) and an archived twin) and ``app2`` (one run
touching the target's function); ``ws2`` holds ``app3`` (a label-smoothing
run). Records are written as ``vmn-exp`` leaves them on disk.
"""
import json
import os

import yaml

TARGET = "0.0.1-dev.target"
TWIN = "0.0.1-dev.twin"
OTHER = "0.0.1-dev.other"
RERUN = "0.0.1-dev.rerun"
ARCHIVED = "0.0.1-dev.archived"
CROSS = "0.0.2-dev.cross"
SMOOTH = "0.0.3-dev.smooth"
LONG_INTENT = "Focal loss, again. " + "x" * 3000
FOCAL = ["loss.py", "train.py"], ["loss.py::focal_loss"]


def _features(files, symbols=(), email=None):
    entry = {"type": "features", "features_version": 1, "source": "capture",
             "changed": {"files": list(files), "symbols": list(symbols)}}
    if email:
        entry["author"] = {"git_user_email": email, "source": "git"}
    return entry


def _intent(text, keywords=()):
    entry = {"type": "intent", "text": text, "source": "user"}
    if keywords:
        entry["keywords"] = list(keywords)
    return entry


def write_run(root, app, verstr, entries=(), second=0, run_state=None, **meta):
    """One record under *root*'s store: metadata, a ``w0`` log of *entries*
    (timestamped), and *run_state* when given."""
    path = os.path.join(root, ".vmn", "store", "runs", app, verstr)
    os.makedirs(os.path.join(path, "log"), exist_ok=True)
    stamp = f"2026-09-21T12:00:{second:02d}Z"
    record = {"format_version": 1, "verstr": verstr, "code_verstr": verstr,
              "timestamp": stamp, "branch": "master", "base_version": "0.0.1", **meta}
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(record, f)
    with open(os.path.join(path, "log", "w0.jsonl"), "w") as f:
        f.writelines(json.dumps({"timestamp": stamp, **entry}) + "\n" for entry in entries)
    if run_state is not None:
        with open(os.path.join(path, "run_state.yml"), "w") as f:
            yaml.dump(run_state, f)


def _metrics(**values):
    return {"type": "metrics", "values": values}


def _params(**values):
    return {"type": "params", "params": values}


def _app1(root):
    goal = {"type": "define_metric", "name": "loss", "goal": "min"}
    write_run(root, "app1", TARGET, [
        _features(*FOCAL, email="alice@x.io"), _params(lr=3e-4), _metrics(loss=0.5), goal,
        _intent("Focal loss for class imbalance", ["focal loss"]),
    ], second=1)
    write_run(root, "app1", TWIN, [
        _features(*FOCAL, email="bob@x.io"), _params(lr=1e-4), _metrics(loss=0.3),
        _intent(LONG_INTENT, ["focal loss"]),
    ], second=2, name="twin", note="focal loss again",
        run_state={"state": "exited", "exit_code": 0})
    write_run(root, "app1", OTHER, [
        _features(["data.py"]), _params(batch=64), _metrics(loss=0.9),
    ], second=3, note="bigger batch")
    write_run(root, "app1", RERUN, [_features(*FOCAL), _params(lr=3e-4)],
              second=4, code_verstr=TARGET)
    write_run(root, "app1", ARCHIVED, [_features(*FOCAL), _params(lr=3e-4)],
              second=5, archived=True)


def make_workspaces(tmp_path):
    """``{ws: root}`` of the two workspaces, their records written."""
    roots = {"ws1": str(tmp_path / "ws1"), "ws2": str(tmp_path / "ws2")}
    for root in roots.values():
        os.makedirs(os.path.join(root, ".vmn"))
    _app1(roots["ws1"])
    write_run(roots["ws1"], "app2", CROSS, [_features(["loss.py"], ["loss.py::focal_loss"])],
              second=6, note="focal loss in another app")
    write_run(roots["ws2"], "app3", SMOOTH, [
        _features(["smooth.py"]), _intent("Label smoothing on imagenet", ["label smoothing"]),
    ], second=7)
    return roots


def client_for(tmp_path, auth=None, **kw):
    """A TestClient over :func:`make_workspaces`' workspaces."""
    from fastapi.testclient import TestClient
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "ui_data"))
    for ws, root in make_workspaces(tmp_path).items():
        manager.attach_path(ws, root)
    return TestClient(create_app(manager, auth=auth, **kw))
