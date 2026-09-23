"""Scale guard: after a cold build, a metric append or a heartbeat must cost a
small fraction of it — they touch one file, not every experiment.

Loose, relative bounds (a quarter of the cold build) so a loaded CI box does
not flake; the incremental paths measure around a few percent.
"""
import json
import os
import time

import yaml

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.core.experiment_index import ExperimentIndex

APP = "app"
RUNS = 3000
STEPS = 50


def _seed(root):
    base = os.path.join(root, ".vmn", APP, "experiments")
    for i in range(RUNS):
        verstr = f"0.0.1-dev.abc1234.def5678.r{i}"
        folder = os.path.join(base, verstr)
        os.makedirs(folder)
        meta = {
            "verstr": verstr, "code_verstr": "0.0.1-dev.abc1234.def5678",
            "timestamp": f"2026-01-01T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}Z",
            "base_version": "0.0.1", "branch": "main", "note": None,
            "dirty_states": ["modified"], "changesets": {".": {"hash": "a" * 40}},
        }
        with open(os.path.join(folder, "metadata.yml"), "w") as f:
            yaml.dump(meta, f)
        with open(os.path.join(folder, "log.w.jsonl"), "w") as f:
            f.write(json.dumps({"timestamp": "2026-01-01T00:00:00Z", "type": "create",
                                "params": {"lr": 0.1, "opt": "adam"}}) + "\n")
            f.writelines(json.dumps({"timestamp": f"2026-01-01T00:01:{step % 60:02d}Z",
                                    "type": "metrics", "step": step,
                                    "values": {"loss": 1.0 / (step + 1), "acc": step / STEPS}}) + "\n" for step in range(STEPS))
        with open(os.path.join(folder, "run_state.yml"), "w") as f:
            f.write("state: finished\nexit_code: 0\nheartbeat: '2026-01-01T00:00:00Z'\n")
    return base


def _timed(index):
    start = time.perf_counter()
    index.refresh()
    rows, states = index.rows(), index.run_states()
    return time.perf_counter() - start, rows, states


def test_append_and_heartbeat_cost_a_fraction_of_the_cold_build(tmp_path):
    base = _seed(str(tmp_path))
    storage = get_snapshot_storage("local", vmn_root_path=str(tmp_path), subdir="experiments")
    index = ExperimentIndex(storage, APP, cache_path=str(tmp_path / "bench.sqlite"))

    cold, rows, _ = _timed(index)
    assert len(rows) == RUNS

    target = rows[RUNS // 2]["verstr"]
    with open(os.path.join(base, target, "log.w.jsonl"), "a") as f:
        f.write(json.dumps({"timestamp": "2027-01-01T00:00:00Z", "type": "metrics",
                            "values": {"loss": 0.0001}}) + "\n")
    append, rows, _ = _timed(index)
    assert rows[RUNS // 2]["metrics"]["loss"] == 0.0001

    state_path = os.path.join(base, rows[7]["verstr"], "run_state.yml")
    with open(state_path, "w") as f:
        f.write("state: finished\nexit_code: 9\nheartbeat: '2026-01-01T00:00:09Z'\n")
    heartbeat, _, states = _timed(index)
    assert states[rows[7]["verstr"]]["exit_code"] == 9

    assert append < 0.25 * cold, (append, cold)
    assert heartbeat < 0.25 * cold, (heartbeat, cold)


def test_a_new_process_starts_warm_from_the_persisted_index(tmp_path):
    _seed(str(tmp_path))
    storage = get_snapshot_storage("local", vmn_root_path=str(tmp_path), subdir="experiments")
    cache = str(tmp_path / "bench.sqlite")
    cold, rows, _ = _timed(ExperimentIndex(storage, APP, cache_path=cache))

    warm, warm_rows, _ = _timed(ExperimentIndex(storage, APP, cache_path=cache))
    assert warm_rows == rows
    assert warm < 0.5 * cold, (warm, cold)
