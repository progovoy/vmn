"""Tests for writer provenance (_writer field injection in merged logs)."""
import json
import os
import tempfile

import yaml

from version_stamp.cli.snapshot import LocalSnapshotStorage


def _make_storage(base_dir, app_name, verstr):
    storage = LocalSnapshotStorage(base_dir)
    safe_verstr = verstr.replace("+", "_plus_")
    snap_dir = os.path.join(base_dir, ".vmn", app_name, "snapshots", safe_verstr)
    os.makedirs(snap_dir, exist_ok=True)
    return storage, snap_dir


def test_merged_log_injects_writer_for_jsonl_entries():
    with tempfile.TemporaryDirectory() as tmp:
        storage, snap_dir = _make_storage(tmp, "myapp", "0.0.1-exp.1")
        entries = [
            {"timestamp": "2026-01-01T00:00:00Z", "type": "metrics", "values": {"loss": 0.5}},
            {"timestamp": "2026-01-01T00:01:00Z", "type": "metrics", "values": {"loss": 0.3}},
        ]
        with open(os.path.join(snap_dir, "log.gpu0.jsonl"), "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        merged = storage.load_merged_log("myapp", "0.0.1-exp.1")
        assert len(merged) == 2
        assert all(e["_writer"] == "gpu0" for e in merged)


def test_merged_log_omits_writer_for_legacy_log_yml():
    with tempfile.TemporaryDirectory() as tmp:
        storage, snap_dir = _make_storage(tmp, "myapp", "0.0.1-exp.2")
        legacy = [
            {"timestamp": "2026-01-01T00:00:00Z", "type": "create"},
        ]
        with open(os.path.join(snap_dir, "log.yml"), "w") as f:
            yaml.dump(legacy, f)

        merged = storage.load_merged_log("myapp", "0.0.1-exp.2")
        assert len(merged) == 1
        assert "_writer" not in merged[0]


def test_merged_log_mixed_legacy_and_writer():
    with tempfile.TemporaryDirectory() as tmp:
        storage, snap_dir = _make_storage(tmp, "myapp", "0.0.1-exp.3")
        legacy = [
            {"timestamp": "2026-01-01T00:00:00Z", "type": "create"},
        ]
        with open(os.path.join(snap_dir, "log.yml"), "w") as f:
            yaml.dump(legacy, f)
        writer_entries = [
            {"timestamp": "2026-01-01T00:01:00Z", "type": "metrics", "values": {"acc": 0.9}},
        ]
        with open(os.path.join(snap_dir, "log.worker1.jsonl"), "w") as f:
            for e in writer_entries:
                f.write(json.dumps(e) + "\n")

        merged = storage.load_merged_log("myapp", "0.0.1-exp.3")
        assert len(merged) == 2
        assert "_writer" not in merged[0]  # legacy entry
        assert merged[1]["_writer"] == "worker1"  # jsonl entry
