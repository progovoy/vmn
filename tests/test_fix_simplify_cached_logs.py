"""Local-first log reads fetch only what the remote has that local lacks."""
import os

import boto3
import pytest
from moto import mock_aws

from version_stamp.cli.snapshot import get_snapshot_storage

BUCKET = "vmn-bucket"
V = "0.0.1-dev.aaa.bbb"


@pytest.fixture
def s3():
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def _host(tmp_path, name):
    return get_snapshot_storage(
        "local",
        vmn_root_path=str(tmp_path / name),
        bucket=BUCKET,
        prefix="exp",
        subdir="experiments",
    )


def _log_gets(storage):
    """Count GetObject calls on log objects made through *storage*'s client."""
    calls = []
    client = storage._remote._s3
    real = client.get_object

    def get_object(**kwargs):
        if "/log." in kwargs.get("Key", ""):
            calls.append(kwargs["Key"])
        return real(**kwargs)

    client.get_object = get_object
    return calls


def _entry(i):
    return {"timestamp": f"2026-01-01T00:00:{i:02d}Z", "type": "metrics", "values": {"i": i}}


def test_reading_a_log_the_remote_only_mirrors_downloads_nothing(s3, tmp_path):
    host = _host(tmp_path, "a")
    host.save("app", V, {"verstr": V, "timestamp": "t"}, {})
    for i in range(3):
        host.append_log_entry("app", V, "w", _entry(i))
    host.sync_log_to_remote("app", V, "w")

    gets = _log_gets(host)
    assert [e["values"]["i"] for e in host.load_merged_log("app", V)] == [0, 1, 2]
    assert gets == []


def test_a_writer_only_the_remote_has_is_fetched(s3, tmp_path):
    a, b = _host(tmp_path, "a"), _host(tmp_path, "b")
    a.save("app", V, {"verstr": V, "timestamp": "t"}, {})
    a.append_log_entry("app", V, "wa", _entry(0))
    a.sync_log_to_remote("app", V, "wa")
    b.append_log_entry("app", V, "wb", _entry(1))  # pulls the record in first
    b.sync_log_to_remote("app", V, "wb")

    merged = a.load_merged_log("app", V)
    assert sorted(e["_writer"] for e in merged) == ["wa", "wb"]


def test_sync_reads_only_the_bytes_past_what_it_shipped(s3, tmp_path):
    host = _host(tmp_path, "a")
    host.save("app", V, {"verstr": V, "timestamp": "t"}, {})
    host.append_log_entry("app", V, "w", _entry(0))
    host.sync_log_to_remote("app", V, "w")

    whole_reads = []
    real = host._local.load_file

    def load_file(app, verstr, filename):
        whole_reads.append(filename)
        return real(app, verstr, filename)

    host._local.load_file = load_file
    host.append_log_entry("app", V, "w", _entry(1))
    host.sync_log_to_remote("app", V, "w")

    assert "log.w.jsonl" not in whole_reads
    fresh = _host(tmp_path, "c")
    assert [e["values"]["i"] for e in fresh.load_merged_log("app", V)] == [0, 1]
