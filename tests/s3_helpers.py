"""Shared helpers for the moto-backed S3 storage tests."""
import collections
import contextlib
import threading

import boto3
from moto import mock_aws

from version_stamp.core.logging import init_stamp_logger

BUCKET = "vmn-bucket"
PREFIX = "exps"


@contextlib.contextmanager
def mocked_bucket(monkeypatch):
    for k, v in dict(
        AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x", AWS_DEFAULT_REGION="us-east-1"
    ).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    try:
        init_stamp_logger()
    except Exception:
        pass
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def s3_storage():
    from version_stamp.cli.snapshot import S3SnapshotStorage

    return S3SnapshotStorage(BUCKET, prefix=PREFIX)


def cached_host(tmp_path, name):
    from version_stamp.cli.snapshot import get_snapshot_storage

    return get_snapshot_storage(
        "local",
        vmn_root_path=str(tmp_path / name),
        bucket=BUCKET,
        prefix=PREFIX,
        subdir="experiments",
    )


def record_calls(client):
    """``[(operation, api params)]`` of every call *client* makes from now on."""
    calls = []
    client.meta.events.register(
        "before-parameter-build.s3",
        lambda event_name, params, **kw: calls.append(
            (event_name.split(".")[-1], dict(params))
        ),
    )
    return calls


def op_counts(calls):
    return collections.Counter(op for op, _ in calls)


def raw_keys(prefix=PREFIX):
    client = boto3.client("s3")
    keys = []
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=BUCKET, Prefix=prefix + "/"
    ):
        keys.extend(o["Key"] for o in page.get("Contents", []))
    return sorted(keys)


def put_raw(key, body):
    boto3.client("s3").put_object(Bucket=BUCKET, Key=key, Body=body)


def meta(verstr, **kw):
    return dict({"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, **kw)


def entry(i, **kw):
    return dict(
        {
            "timestamp": f"2026-01-01T00:00:{i:02d}Z",
            "type": "metrics",
            "values": {"i": i},
        },
        **kw,
    )


def concurrently(n, wrapped):
    """Wrap *wrapped* so its first *n* calls must overlap in time.

    Each call waits on a shared barrier before proceeding, so calls made one
    after the other break the barrier (``BrokenBarrierError``) instead of
    silently passing.
    """
    barrier = threading.Barrier(n, timeout=5)
    seen = []
    lock = threading.Lock()

    def call(*args, **kwargs):
        with lock:
            first = len(seen) < n
            seen.append(True)
        if first:
            barrier.wait()
        return wrapped(*args, **kwargs)

    return call
