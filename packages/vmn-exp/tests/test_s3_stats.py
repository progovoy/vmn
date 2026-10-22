"""Process-wide S3 request statistics (``vmn_exp.storage.s3_stats``) for the
``vmn-exp ui`` diagnostic dump."""
import threading

import boto3
import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ClientError
from moto import mock_aws
from vmn_exp.storage import s3_stats
from vmn_exp.storage.s3 import S3SnapshotStorage
from vmn_exp.storage.s3_base import MAX_POOL_CONNECTIONS


@pytest.fixture
def bucket(monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket="stats-bkt")
        yield "stats-bkt"


def _op(name):
    return s3_stats.s3_stats()["operations"].get(name, {})


def _count(name):
    return _op(name).get("count", 0)


def test_counts_each_operation_through_the_storage_backend(bucket):
    before = {op: _count(op) for op in ("PutObject", "ListObjectsV2", "GetObject")}
    storage = S3SnapshotStorage(bucket, prefix="exps/runs")
    storage.save("my_app", "0.0.1-dev.abc", {"verstr": "0.0.1-dev.abc"}, {})
    storage.list_apps()
    storage.load("my_app", "0.0.1-dev.abc")

    for op, n in before.items():
        assert _count(op) > n, op
    get = _op("GetObject")
    assert get["latency_ms"]["max"] >= get["latency_ms"]["p95"] >= get["latency_ms"]["p50"] >= 0
    assert get["bytes_read"] > 0
    assert get["in_flight"] == 0


def test_reports_clients_and_their_pool(bucket):
    created = s3_stats.s3_stats()["clients_created"]
    S3SnapshotStorage(bucket, prefix="exps/runs")
    stats = s3_stats.s3_stats()
    assert stats["clients_created"] == created + 1
    assert MAX_POOL_CONNECTIONS in stats["max_pool_connections"]


def test_counts_errors_by_code(bucket):
    storage = S3SnapshotStorage(bucket, prefix="exps/runs")
    errors = dict(_op("GetObject").get("errors", {}))
    with pytest.raises(ClientError):
        storage._s3.get_object(Bucket=bucket, Key="missing/metadata.yml")
    assert _op("GetObject")["errors"]["NoSuchKey"] == errors.get("NoSuchKey", 0) + 1


def test_in_flight_visible_while_a_call_is_blocked(bucket):
    storage = S3SnapshotStorage(bucket, prefix="exps/runs")
    entered, release = threading.Event(), threading.Event()

    def block(**_):
        entered.set()
        release.wait(10)

    storage._s3.meta.events.register_first("before-send.s3.HeadBucket", block)
    worker = threading.Thread(target=storage._s3.head_bucket, kwargs={"Bucket": bucket})
    worker.start()
    try:
        assert entered.wait(10)
        stats = s3_stats.s3_stats()
        assert stats["operations"]["HeadBucket"]["in_flight"] >= 1
        oldest = [r for r in stats["in_flight"] if r["operation"] == "HeadBucket"]
        assert oldest and oldest[0]["age_ms"] >= 0
        assert stats["clients"][0]["in_flight"] >= 1
    finally:
        release.set()
        worker.join(10)
    assert _op("HeadBucket")["in_flight"] == 0


class _Raw:
    def stream(self, **_):
        yield b""


def test_counts_retries(bucket):
    storage = S3SnapshotStorage(bucket, prefix="exps/runs")
    retries = _op("HeadBucket").get("retries", 0)
    failures = []

    def fail_once(request, **_):
        if not failures:
            failures.append(1)
            return AWSResponse(request.url, 500, {}, _Raw())
        return None

    storage._s3.meta.events.register_first("before-send.s3.HeadBucket", fail_once)
    storage._s3.head_bucket(Bucket=bucket)
    assert _op("HeadBucket")["retries"] == retries + 1


def test_histogram_memory_is_bounded():
    hist = s3_stats.LatencyHistogram()
    for i in range(100_000):
        hist.add(i % 1000)
    size = len(hist.buckets)
    hist.add(10 ** 9)
    assert len(hist.buckets) == size
    summary = hist.summary()
    assert summary["max"] == 10 ** 9
    assert 200 <= summary["p50"] <= 1000
    assert summary["p50"] <= summary["p95"] <= summary["max"]


def test_a_broken_hook_never_raises_into_the_request():
    hooks = s3_stats.ClientStats(max_pool_connections=10)
    hooks.before_call(context=None)  # no model, no dict to store the start in
    hooks.after_call(context=None, parsed=None, http_response=None)
    hooks.after_call_error(context=None, exception=None)


def test_listeners_see_each_call_on_the_calling_thread(bucket):
    storage = S3SnapshotStorage(bucket, prefix="exps/runs")
    storage._s3.put_object(Bucket=bucket, Key="a/b.yml", Body=b"hello")
    calls = []

    def listen(call):
        calls.append((threading.get_ident(), call))

    s3_stats.add_listener(listen)
    try:
        storage._s3.get_object(Bucket=bucket, Key="a/b.yml")["Body"].read()
        with pytest.raises(ClientError):
            storage._s3.get_object(Bucket=bucket, Key="a/missing.yml")
    finally:
        s3_stats.remove_listener(listen)
    storage._s3.head_object(Bucket=bucket, Key="a/b.yml")

    assert [c.key for _, c in calls] == ["a/b.yml", "a/missing.yml"]
    assert {t for t, _ in calls} == {threading.get_ident()}
    ok, missing = (c for _, c in calls)
    assert ok.operation == "GetObject" and ok.status == 200 and ok.error is None
    assert ok.bytes_read == 5 and ok.retries == 0 and ok.duration_ms >= 0
    assert missing.status == 404 and missing.error == "NoSuchKey"


def test_a_failing_listener_never_breaks_the_call(bucket):
    storage = S3SnapshotStorage(bucket, prefix="exps/runs")

    def broken(call):
        raise RuntimeError("listener bug")

    s3_stats.add_listener(broken)
    try:
        storage._s3.head_bucket(Bucket=bucket)
    finally:
        s3_stats.remove_listener(broken)
