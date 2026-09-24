"""Scale guard: a refresh that finds nothing new must not list every finished
record's files — that per-request stat of the whole store is what made the ui
slow at 5k+ runs. Counts listed records instead of timing, so it cannot flake.
"""
import json
import os

import yaml

from version_stamp.cli.snapshot import LocalSnapshotStorage
from version_stamp.core.experiment_index import ExperimentIndex

APP = "app"
RUNS = 2000


def _seed(root):
    base = os.path.join(root, ".vmn", APP, "experiments")
    for i in range(RUNS):
        verstr = f"0.0.1-dev.abc1234.def5678.r{i}"
        folder = os.path.join(base, verstr)
        os.makedirs(folder)
        meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:{i // 60 % 60:02d}:{i % 60:02d}Z"}
        with open(os.path.join(folder, "metadata.yml"), "w") as f:
            yaml.dump(meta, f)
        with open(os.path.join(folder, "log.w.jsonl"), "w") as f:
            f.write(json.dumps({"timestamp": "t", "type": "metrics", "values": {"loss": i}}) + "\n")
        with open(os.path.join(folder, "run_state.yml"), "w") as f:
            f.write("state: finished\nexit_code: 0\n")


class CountingStorage(LocalSnapshotStorage):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.listed = 0
        self.full_listings = 0

    def list_files(self, app_name, keys=None):
        files = super().list_files(app_name, keys=keys)
        self.listed += len(files)
        self.full_listings += keys is None
        return files


def test_a_no_change_refresh_lists_no_finished_record(tmp_path):
    _seed(str(tmp_path))
    storage = CountingStorage(str(tmp_path), subdir="experiments")
    index = ExperimentIndex(storage, APP, cache_path=str(tmp_path / "idx.sqlite"))
    index.refresh()
    assert len(index.rows()) == RUNS

    storage.listed = storage.full_listings = 0
    for _ in range(5):
        index.refresh()

    assert storage.full_listings == 0
    assert storage.listed == 0
    assert len(index.snapshot().rows) == RUNS
