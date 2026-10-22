"""What the S3 calls of the ``vmn-exp ui`` dump were for: each call's key
classified into a fixed set of kinds (``s3.by_kind``) and the last failed
calls with their keys (``s3.recent_failures``)."""
import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from vmn_exp.storage import s3_stats
from vmn_exp.storage.s3 import S3SnapshotStorage
from vmn_exp.storage.s3_kinds import KINDS, classify

RUN = "vmn/runs/my_app/0.0.1-dev.abc.w1"


@pytest.mark.parametrize("operation,key,kind", [
    ("GetObject", f"{RUN}/metadata.yml", "metadata.yml"),
    ("HeadObject", f"{RUN}/run_state.yml", "run_state.yml"),
    ("GetObject", f"{RUN}/log/w1~a@000003.jsonl", "log segment"),
    ("GetObject", f"{RUN}/log/w1~a.jsonl", "log segment"),
    ("GetObject", f"{RUN}/metrics/w1~a.vms", "metric stream"),
    ("GetObject", f"{RUN}/metrics/w1~a@000002.vms", "metric stream"),
    ("GetObject", f"{RUN}/metrics/w1~a@000000-000009.vmx", "metric index (.vmx)"),
    ("PutObject", f"{RUN}/children/0.0.1-dev.def.w1", "child marker"),
    ("ListObjectsV2", f"{RUN}/children/", "children listing"),
    ("ListObjectsV2", "vmn/runs/my_app/", "run listing"),
    ("ListObjectsV2", f"{RUN}/", "run listing"),
    ("ListObjectsV2", "vmn/journal/202610221530/", "journal"),
    ("GetObject", "vmn/journal/202610221530/x.yml", "journal"),
    ("GetObject", "vmn/comments/my_app/c1.yml", "comments"),
    ("GetObject", "vmn/reports/r1/report.yml", "reports"),
    ("GetObject", "vmn/code/my_app/0.0.1-dev.abc.ff/metadata.yml", "code"),
    ("GetObject", f"{RUN}/outputs/output.log", "outputs"),
    ("GetObject", f"{RUN}/artifacts/model.pt", "artifacts"),
    ("GetObject", "vmn/store.yml", "store.yml"),
    ("GetObject", "store.yml", "store.yml"),
    ("GetObject", "vmn/snapshots/my_app/v/metadata.yml", "snapshots"),
    ("GetObject", "vmn/registry/model/v1.yml", "registry"),
    ("GetObject", "elsewhere/thing.bin", "other"),
    ("DeleteObjects", "", "other"),
])
def test_classify_names_what_a_key_is(operation, key, kind):
    assert classify(operation, key) == kind
    assert kind in KINDS


def _bucket_env(monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def client(monkeypatch):
    _bucket_env(monkeypatch)
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket="kinds-bkt")
        yield S3SnapshotStorage("kinds-bkt", prefix="vmn")._s3


def _kind(name):
    return s3_stats.s3_stats()["by_kind"].get(name, {})


def test_by_kind_counts_calls_and_their_errors_per_operation_and_kind(client):
    before = _kind("GetObject metadata.yml")
    misses = before.get("errors", {}).get("NoSuchKey", 0)
    client.put_object(Bucket="kinds-bkt", Key=f"{RUN}/metadata.yml", Body=b"a: 1")
    client.get_object(Bucket="kinds-bkt", Key=f"{RUN}/metadata.yml")["Body"].read()
    with pytest.raises(ClientError):
        client.get_object(Bucket="kinds-bkt", Key="vmn/runs/my_app/gone/metadata.yml")
    client.list_objects_v2(Bucket="kinds-bkt", Prefix=f"{RUN}/children/")

    after = _kind("GetObject metadata.yml")
    assert after["count"] == before.get("count", 0) + 2
    assert after["errors"]["NoSuchKey"] == misses + 1
    assert set(after["latency_ms"]) == {"p50", "p95", "max"}
    assert _kind("ListObjectsV2 children listing")["count"] >= 1
    assert _kind("PutObject metadata.yml")["count"] >= 1


def test_recent_failures_name_the_key_newest_first(client):
    for name in ("first", "second"):
        with pytest.raises(ClientError):
            client.get_object(Bucket="kinds-bkt", Key=f"vmn/runs/my_app/{name}/run_state.yml")
    failures = s3_stats.s3_stats()["recent_failures"]
    assert [f["key"] for f in failures[:2]] == [
        "vmn/runs/my_app/second/run_state.yml", "vmn/runs/my_app/first/run_state.yml"]
    newest = failures[0]
    assert newest["operation"] == "GetObject"
    assert newest["error"] == "NoSuchKey" and newest["status"] == 404
    assert newest["age_sec"] >= 0


def test_the_failure_ring_is_bounded():
    hooks = s3_stats.ClientStats(max_pool_connections=1)
    model = type("Model", (), {"name": "HeadObject"})()
    for i in range(s3_stats.FAILURES_SHOWN * 3):
        context = {"_vmn_s3_key": f"vmn/runs/a/v{i}/run_state.yml"}
        hooks.before_call(model=model, context=context)
        hooks.after_call(context=context, parsed={"Error": {"Code": "404"}},
                         http_response=type("R", (), {"status_code": 404})())
    failures = s3_stats.s3_stats()["recent_failures"]
    assert len(failures) == s3_stats.FAILURES_SHOWN
    assert failures[0]["key"] == f"vmn/runs/a/v{s3_stats.FAILURES_SHOWN * 3 - 1}/run_state.yml"
