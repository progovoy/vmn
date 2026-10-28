"""vmn's S3 clients cap the calls in flight per key prefix
(``vmn_exp.storage.s3_prefix_cap``): S3 throttles per prefix (~3,500 PUT /
5,500 GET a second), so one app's fan-outs queue behind each other instead of
drawing ``SlowDown``s, while other apps' calls go on."""
import threading
import uuid

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from vmn_exp.storage import s3_prefix_cap, s3_stats
from vmn_exp.storage.s3 import S3SnapshotStorage
from vmn_exp.storage.s3_base import MAX_POOL_CONNECTIONS

ENV = "VMN_EXP_S3_PREFIX_CONCURRENCY"


@pytest.fixture
def client(monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        bucket = f"cap-{uuid.uuid4().hex[:12]}"  # caps are per (bucket, prefix)
        boto3.client("s3").create_bucket(Bucket=bucket)
        yield bucket, S3SnapshotStorage(bucket, prefix="exps/runs")._s3


def _head(s3, bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except ClientError:
        pass  # missing: a 404 still takes (and gives back) a slot


class _Gate:
    """Blocks every HeadObject inside the call (so inside its slot) and counts
    how many are in at once."""

    def __init__(self, s3):
        self.lock = threading.Lock()
        self.inside = self.peak = 0
        self.entered = threading.Semaphore(0)
        self.release = threading.Event()
        s3.meta.events.register_first("before-send.s3.HeadObject", self.block)

    def block(self, **_):
        with self.lock:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
        self.entered.release()
        self.release.wait(10)
        with self.lock:
            self.inside -= 1


def _start(s3, bucket, keys):
    threads = [threading.Thread(target=_head, args=(s3, bucket, k), daemon=True) for k in keys]
    for t in threads:
        t.start()
    return threads


def _cap(bucket, prefix):
    return s3_prefix_cap._caps[(bucket, prefix)].as_dict()


def _dumped(bucket, prefix):
    rows = s3_stats.s3_stats()["prefix_caps"]["prefixes"]
    return next(r for r in rows if r["bucket"] == bucket and r["prefix"] == prefix)


@pytest.mark.parametrize("key, prefix", [
    ("exps/runs/my_app/0.0.1-dev.abc/metadata.yml", "exps/runs/my_app"),
    ("exps/runs/my_app/", "exps/runs/my_app"),
    ("exps/runs/", "exps/runs"),
    ("vmn/journal/202610281001/x.yml", "vmn/journal"),
    ("vmn/journal/202610281001/", "vmn/journal"),
    ("vmn/journal/", "vmn/journal"),
    ("vmn/store.yml", "vmn"),
    ("a/b.yml", "a"),
    ("", ""),
])
def test_the_prefix_is_the_area_and_its_scope(key, prefix):
    assert s3_prefix_cap.prefix_of(key) == prefix


def test_journal_partitions_share_one_cap(client):
    bucket, s3 = client
    for minute in range(30):
        s3.list_objects_v2(Bucket=bucket, Prefix=f"vmn/journal/2026102810{minute:02d}/")
        _head(s3, bucket, f"vmn/journal/2026102810{minute:02d}/x")
    assert [p for b, p in s3_prefix_cap._caps if b == bucket] == ["vmn/journal"]


def test_calls_under_one_prefix_wait_for_a_slot(client, monkeypatch):
    monkeypatch.setenv(ENV, "2")
    bucket, s3 = client
    gate = _Gate(s3)
    threads = _start(s3, bucket, [f"exps/runs/app_a/v{i}/metadata.yml" for i in range(5)])
    try:
        assert gate.entered.acquire(timeout=10) and gate.entered.acquire(timeout=10)
        assert not gate.entered.acquire(timeout=0.5)
        row = _dumped(bucket, "exps/runs/app_a")  # waiting: listed first in the diag dump
        assert (row["limit"], row["in_flight"], row["waiting"]) == (2, 2, 3)
    finally:
        gate.release.set()
        for t in threads:
            t.join(10)
    assert gate.peak == 2
    row = _cap(bucket, "exps/runs/app_a")
    assert row["in_flight"] == row["waiting"] == 0
    assert row["peak_in_flight"] == 2 and row["waits"] == 3
    assert row["wait_ms_max"] > 0


def test_another_prefix_is_not_held_up(client, monkeypatch):
    monkeypatch.setenv(ENV, "1")
    bucket, s3 = client
    gate = _Gate(s3)
    threads = _start(s3, bucket, ["exps/runs/app_a/v1/metadata.yml"])
    try:
        assert gate.entered.acquire(timeout=10)
        threads += _start(s3, bucket, ["exps/runs/app_b/v1/metadata.yml"])
        assert gate.entered.acquire(timeout=10)  # app_b is in while app_a holds its slot
    finally:
        gate.release.set()
        for t in threads:
            t.join(10)


def test_a_call_made_while_holding_the_slot_does_not_deadlock(client, monkeypatch):
    monkeypatch.setenv(ENV, "1")
    bucket, s3 = client
    nested = []

    def call_again(**_):
        if not nested:
            nested.append(1)
            _head(s3, bucket, "exps/runs/app_a/v2/metadata.yml")
            nested.append(2)

    s3.meta.events.register_first("before-send.s3.HeadObject", call_again)
    worker = threading.Thread(target=_head, args=(s3, bucket, "exps/runs/app_a/v1/metadata.yml"),
                              daemon=True)  # a deadlock fails the test, never hangs it
    worker.start()
    worker.join(10)
    assert not worker.is_alive() and nested == [1, 2]
    _head(s3, bucket, "exps/runs/app_a/v3/metadata.yml")  # the slot came back
    assert _cap(bucket, "exps/runs/app_a")["in_flight"] == 0


def test_a_failed_call_gives_its_slot_back(client, monkeypatch):
    monkeypatch.setenv(ENV, "1")
    bucket, s3 = client

    def refuse(**_):
        raise ConnectionError("network down")

    s3.meta.events.register_first("before-send.s3.GetObject", refuse)
    for _ in range(3):
        with pytest.raises(Exception):
            s3.get_object(Bucket=bucket, Key="exps/runs/app_a/v1/metadata.yml")
    _head(s3, bucket, "exps/runs/app_a/v1/metadata.yml")
    assert _cap(bucket, "exps/runs/app_a")["in_flight"] == 0


@pytest.mark.parametrize("value", [None, "0", "-3", "lots"])
def test_unset_zero_or_invalid_keeps_the_default(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, value)
    assert s3_prefix_cap.limit() == s3_prefix_cap.DEFAULT_PREFIX_CONCURRENCY
    assert 0 < s3_prefix_cap.DEFAULT_PREFIX_CONCURRENCY <= MAX_POOL_CONNECTIONS


def test_the_env_var_sets_the_cap(monkeypatch):
    monkeypatch.setenv(ENV, "7")
    assert s3_prefix_cap.limit() == 7
