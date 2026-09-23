"""Pure-S3 appends stay in one log object and never lose a concurrent entry."""
import json
import os

import boto3
import pytest
from moto import mock_aws

from version_stamp.cli.snapshot import S3SnapshotStorage

BUCKET = "vmn-bucket"
VERSTR = "1.0.0-dev.aaa.bbb"
LOG_KEY = f"exp/app/{VERSTR}/log.writer.jsonl"


@pytest.fixture
def s3():
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def _storage():
    storage = S3SnapshotStorage(BUCKET, prefix="exp")
    storage.save("app", VERSTR, {"verstr": VERSTR, "timestamp": "t0"}, {})
    return storage


def _log_lines(s3):
    body = s3.get_object(Bucket=BUCKET, Key=LOG_KEY)["Body"].read().decode()
    return [json.loads(line) for line in body.splitlines() if line.strip()]


def test_appends_land_in_the_single_writer_object(s3):
    storage = _storage()
    for i in range(3):
        storage.append_log_entry("app", VERSTR, "writer", {"timestamp": f"t{i}", "i": i})

    assert [e["i"] for e in _log_lines(s3)] == [0, 1, 2]


def test_an_append_racing_between_read_and_write_is_not_lost(s3):
    first, second = _storage(), S3SnapshotStorage(BUCKET, prefix="exp")
    first.append_log_entry("app", VERSTR, "writer", {"timestamp": "t0", "i": 0})

    real_get = first._s3.get_object
    raced = []

    def get_then_race(**kwargs):
        resp = real_get(**kwargs)
        if kwargs.get("Key") == LOG_KEY and not raced:
            raced.append(True)
            # Another process appends after we read, before we write back.
            second.append_log_entry("app", VERSTR, "writer", {"timestamp": "t1", "i": 1})
        return resp

    first._s3.get_object = get_then_race
    first.append_log_entry("app", VERSTR, "writer", {"timestamp": "t2", "i": 2})

    assert sorted(e["i"] for e in _log_lines(s3)) == [0, 1, 2]
