"""``append_log_entries``: many log entries in one write, on every backend."""
import json
import os

import pytest
from s3_helpers import meta, mocked_bucket, record_calls, s3_storage

from version_stamp.cli import snapshot_storage_local
from version_stamp.cli.experiment import _get_experiment_storage
from version_stamp.cli.snapshot import CachedSnapshotStorage, LocalSnapshotStorage
from version_stamp.core.experiment_logfiles import log_object_name
from version_stamp.core.logging import init_stamp_logger

V = "1.0.0-dev.aaa.bbb"


def _entries(n):
    return [{"timestamp": f"t{i:04d}", "type": "metrics", "values": {"i": i}} for i in range(n)]


def _values(storage):
    log = storage.load_merged_log("app", V)
    return [e["values"]["i"] for e in log if e.get("type") == "metrics"]


@pytest.fixture(autouse=True)
def _logger():
    try:
        init_stamp_logger()
    except Exception:
        pass


@pytest.fixture
def local(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    st.save("app", V, meta(V), {})
    return st


def test_local_batch_is_one_write_of_whole_lines(local, monkeypatch):
    writes = []
    real_write = os.write
    monkeypatch.setattr(
        snapshot_storage_local.os,
        "write",
        lambda fd, data: writes.append(data) or real_write(fd, data),
    )

    assert local.append_log_entries("app", V, "w", _entries(100)) is True

    assert len(writes) == 1
    assert writes[0].endswith(b"\n") and writes[0].count(b"\n") == 100
    assert _values(local) == list(range(100))


def test_local_batch_bumps_the_record_signature_once(local, monkeypatch):
    touched = []
    real_utime = os.utime
    monkeypatch.setattr(
        snapshot_storage_local.os,
        "utime",
        lambda path, *a, **k: touched.append(path) or real_utime(path, *a, **k),
    )

    local.append_log_entries("app", V, "w", _entries(50))

    assert touched == [local._snapshot_dir("app", V)]


def test_local_batch_never_resurrects_a_missing_record(local):
    assert local.append_log_entries("app", "9.9.9-dev.gone", "w", _entries(3)) is False
    assert not os.path.exists(local._snapshot_dir("app", "9.9.9-dev.gone"))


def test_local_batch_appends_after_single_entries(local):
    local.append_log_entry("app", V, "w", _entries(1)[0])
    local.append_log_entries("app", V, "w", _entries(3)[1:])

    path = os.path.join(local._snapshot_dir("app", V), log_object_name("w"))
    with open(path) as f:
        assert [json.loads(line)["values"]["i"] for line in f] == [0, 1, 2]


def test_an_empty_batch_writes_nothing(local):
    assert local.append_log_entries("app", V, "w", []) is True
    assert _values(local) == []


def test_cached_storage_batches_into_its_local_copy(tmp_path):
    cached = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path), "experiments"))
    cached.save("app", V, meta(V), {})

    assert cached.append_log_entries("app", V, "w", _entries(20)) is True
    assert _values(cached) == list(range(20))


@pytest.fixture
def bucket(monkeypatch):
    monkeypatch.delenv("VMN_EXPERIMENT_DIR", raising=False)
    with mocked_bucket(monkeypatch):
        yield


def test_s3_batch_is_one_put(bucket):
    storage = s3_storage()
    storage.save("app", V, meta(V), {})
    calls = record_calls(storage._s3)

    storage.append_log_entries("app", V, "w", _entries(30))

    puts = [p["Key"] for op, p in calls if op == "PutObject" and "/log." in p["Key"]]
    assert len(puts) == 1
    assert _values(storage) == list(range(30))


def test_s3_batch_on_a_segmented_log_adds_one_segment(bucket):
    storage = s3_storage()
    storage.save("app", V, meta(V), {})
    storage.put_log_segment("app", V, "w", 1, b'{"timestamp": "a", "type": "note"}\n')

    storage.append_log_entries("app", V, "w", _entries(5))

    assert _values(storage) == list(range(5))
    assert len(storage.log_objects("app", V, "w")) == 2


def test_direct_s3_pod_batches_through_its_buffer(bucket):
    pod = _get_experiment_storage(None, {"bucket": "vmn-bucket", "prefix": "exps"})
    pod.create_exclusive("app", V, meta(V), {})

    assert pod.append_log_entries("app", V, "w", _entries(10)) is True
    pod.sync_log_to_remote("app", V, "w")

    assert _values(s3_storage()) == list(range(10))
