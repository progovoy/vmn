"""Tests for writer provenance (_writer field injection in merged logs)."""
import json
import os
import tempfile

import yaml

from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.areas import local_store_root


def _make_storage(base_dir, app_name, verstr):
    storage = LocalSnapshotStorage(local_store_root(base_dir))
    safe_verstr = verstr.replace("+", "_plus_")
    snap_dir = os.path.join(base_dir, ".vmn", "store", "snapshots", app_name, safe_verstr)
    os.makedirs(snap_dir, exist_ok=True)
    return storage, snap_dir


def test_merged_log_injects_writer_for_jsonl_entries():
    with tempfile.TemporaryDirectory() as tmp:
        storage, snap_dir = _make_storage(tmp, "myapp", "0.0.1-exp.1")
        entries = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "metrics",
                "values": {"loss": 0.5},
            },
            {
                "timestamp": "2026-01-01T00:01:00Z",
                "type": "metrics",
                "values": {"loss": 0.3},
            },
        ]
        os.makedirs(os.path.dirname(os.path.join(snap_dir, "log/gpu0.jsonl")), exist_ok=True)
        with open(os.path.join(snap_dir, "log/gpu0.jsonl"), "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        merged = storage.load_merged_log("myapp", "0.0.1-exp.1")
        assert len(merged) == 2
        assert all(e["_writer"] == "gpu0" for e in merged)


def test_merged_log_ignores_a_v1_log_yml():
    with tempfile.TemporaryDirectory() as tmp:
        storage, snap_dir = _make_storage(tmp, "myapp", "0.0.1-exp.3")
        legacy = [
            {"timestamp": "2026-01-01T00:00:00Z", "type": "create"},
        ]
        with open(os.path.join(snap_dir, "log.yml"), "w") as f:
            yaml.dump(legacy, f)
        writer_entries = [
            {
                "timestamp": "2026-01-01T00:01:00Z",
                "type": "metrics",
                "values": {"acc": 0.9},
            },
        ]
        os.makedirs(os.path.dirname(os.path.join(snap_dir, "log/worker1.jsonl")), exist_ok=True)
        with open(os.path.join(snap_dir, "log/worker1.jsonl"), "w") as f:
            for e in writer_entries:
                f.write(json.dumps(e) + "\n")

        merged = storage.load_merged_log("myapp", "0.0.1-exp.3")
        assert len(merged) == 1
        assert merged[0]["_writer"] == "worker1"
