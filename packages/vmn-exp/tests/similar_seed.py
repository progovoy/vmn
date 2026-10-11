"""Runs seeded straight into a store for the ``vmn-exp similar`` and reader
tests: a record, its create entry and whatever facts a test gives it
(features, intent, params, metrics, a goal declaration, a run state)."""
import datetime

import yaml
from vmn_exp.core.features import FEATURES_VERSION
from vmn_exp.core.status import RUN_STATE_FILE

WRITER = "w"
TRAIN_STEP = "train.py::train_step"


def verstr(n, commit="aaaaaaa"):
    """A dev verstr of its own code (unique per *n*)."""
    return f"0.0.1-dev.{commit}.{n:07d}"


def features(files=(), symbols=(), commits=(), author=None):
    value = {"changed": {"files": list(files), "symbols": list(symbols)}}
    if commits:
        value["commits"] = list(commits)
    if author:
        value["author"] = {"git_user_email": author, "source": "git"}
    return value


def seed(storage, app, v, *, ts="2026-01-01T00:00:00Z", code=None, parent=None, name=None,
         note=None, archived=False, params=None, metrics=None, goal=None, changes=None,
         intent=None, exit_code=None):
    """A run *v* of *app*. *changes* is a :func:`features` value; *goal*
    ``(metric, "min"|"max")`` declares that metric's goal; *exit_code* None
    leaves the run ``created``."""
    meta = {"verstr": v, "timestamp": ts, "code_verstr": code or v, "base_version": "0.0.1",
            "parent": parent, "name": name, "note": note, "archived": archived}
    storage.save(app, v, meta, {})
    log = [{"type": "create", "note": None, "params": params or {}}]
    if changes is not None:
        log.append(dict(changes, type="features", features_version=FEATURES_VERSION,
                        source="capture"))
    if intent is not None:
        log.append({"type": "intent", "source": "user", **intent})
    if goal is not None:
        log.append({"type": "define_metric", "name": goal[0], "goal": goal[1]})
    if metrics:
        log.append({"type": "metrics", "values": metrics})
    for entry in log:
        storage.append_log_entry(app, v, WRITER, dict(entry, timestamp=ts))
    if exit_code is not None:
        finished(storage, app, v, exit_code)
    return v


def finished(storage, app, v, exit_code=0):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    storage.save_file(app, v, RUN_STATE_FILE, yaml.safe_dump({
        "state": "finished", "pid": 1, "host": "h", "started_at": stamp,
        "heartbeat": stamp, "heartbeat_interval_sec": 30, "exit_code": exit_code}))
