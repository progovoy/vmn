"""A deterministic run tree for the run-detail payload tests: an outer run
with env.yml, metrics and an artifact, a failed child with an output log,
and a succeeded child."""
import json

import yaml

from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"
OUTER = "1.0.0-dev.a"
FAILED = OUTER + ".r2"
DONE = OUTER + ".r3"
VERSTRS = (OUTER, FAILED, DONE)


def _ts(i):
    return f"2026-01-01T00:00:{i:02d}.000000Z"


def _record(storage, verstr, idx, parent=None, state=None):
    meta = {"verstr": verstr, "timestamp": _ts(idx), "code_verstr": OUTER,
            "has_working_tree_patch": False, "has_local_commits_patch": False,
            "has_untracked_files": False}
    if parent:
        meta["parent"] = parent
    storage.save(APP, verstr, meta, {})
    entries = [{"timestamp": _ts(idx), "type": "create", "params": {"lr": 0.1, "epochs": 5}}]
    entries += [{"timestamp": _ts(idx + i), "type": "metrics", "step": i,
                 "values": {"loss": 1.0 / i}} for i in range(1, 4)]
    for entry in entries:
        storage.append_log_entry(APP, verstr, "w", entry)
    if state:
        storage.save_file(APP, verstr, RUN_STATE_FILE, yaml.dump(state))


def build(root):
    storage = LocalSnapshotStorage(root, area="runs")
    _record(storage, OUTER, 0, state={"state": "finished", "exit_code": 0})
    storage.save_file(APP, OUTER, "env.yml", yaml.dump({"python": "3.11", "packages": {"a": "1"}}))
    _record(storage, FAILED, 10, parent=OUTER, state={"state": "finished", "exit_code": 3})
    storage.save_file(APP, FAILED, "outputs/output.log", "line one\nboom\n")
    _record(storage, DONE, 20, parent=OUTER, state={"state": "finished", "exit_code": 0})
    return storage


def edges(storage, app_name):
    return {FAILED: OUTER, DONE: OUTER}


# Clock-dependent: how long ago the run state was written.
_VOLATILE = ("stale_sec",)


def _stable(value):
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def canonical(detail):
    """*detail* as stable JSON text, less its clock-dependent fields."""
    return json.dumps(_stable(json.loads(json.dumps(detail, default=str))),
                      sort_keys=True, indent=1)
