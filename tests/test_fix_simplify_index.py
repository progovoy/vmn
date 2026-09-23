"""The index re-sorts only when order can change, and refreshes remote records
concurrently."""
import json
import os
import threading

import pytest

from version_stamp.cli.snapshot import LocalSnapshotStorage
from version_stamp.core.experiment_index import ExperimentIndex


@pytest.fixture
def storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), subdir="experiments")


def _record(storage, i):
    v = f"0.0.1-dev.r{i:03d}"
    storage.save("app", v, {"verstr": v, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
    storage.append_log_entry("app", v, "w", {"timestamp": "t", "type": "metrics", "values": {"i": i}})
    return v


def _count_sorts(index, monkeypatch):
    calls = []
    real = index._sorted_keys

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(index, "_sorted_keys", counting)
    return calls


def test_a_grown_log_or_a_heartbeat_does_not_resort(storage, monkeypatch):
    versions = [_record(storage, i) for i in range(3)]
    index = ExperimentIndex(storage, "app").refresh()
    sorts = _count_sorts(index, monkeypatch)

    storage.append_log_entry("app", versions[0], "w", {"timestamp": "u", "type": "metrics", "values": {"i": 9}})
    storage.save_file("app", versions[1], "run_state.yml", "state: running\n")
    index.refresh()

    assert sorts == []
    assert index.rows()[0]["metrics"] == {"i": 9}


def test_a_new_record_resorts(storage, monkeypatch):
    _record(storage, 1)
    index = ExperimentIndex(storage, "app").refresh()
    sorts = _count_sorts(index, monkeypatch)

    _record(storage, 0)
    index.refresh()

    assert sorts == [1]
    assert [r["verstr"] for r in index.rows()] == ["0.0.1-dev.r000", "0.0.1-dev.r001"]


def test_remote_records_are_refreshed_concurrently(storage, monkeypatch):
    for i in range(24):
        _record(storage, i)
    monkeypatch.setattr(storage, "is_remote", lambda: True, raising=False)
    index = ExperimentIndex(storage, "app")
    threads = set()
    real = index._update

    def tracking(*args):
        threads.add(threading.get_ident())
        return real(*args)

    monkeypatch.setattr(index, "_update", tracking)
    index.refresh()

    assert len(threads) > 1
    assert [r["metrics"]["i"] for r in index.rows()] == list(range(24))
