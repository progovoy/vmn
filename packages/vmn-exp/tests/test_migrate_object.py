"""``vmn-exp migrate`` on object stores: S3 (moto), GCS and Azure (fakes)."""
import boto3
import pytest
import yaml
from moto import mock_aws

from migrate_fixtures import (
    ObjectRaw, expected_v2_keys, log_paths, object_key, v1_records, write_v1,
)
from object_store_fakes import FakeContainerClient, FakeGCSClient, MatchConditions
from vmn_exp.cli.migrate import migrate_objects, run_migrate
from vmn_exp.storage.store_marker import forget_checked


@pytest.fixture(autouse=True)
def _fresh_marker_cache():
    forget_checked()
    yield
    forget_checked()


@pytest.fixture
def s3(monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket="bkt")
        yield ObjectRaw(client, "bkt")


def _client(kind):
    if kind == "gs":
        from vmn_exp.storage.gcs import GCSObjectClient

        return GCSObjectClient(FakeGCSClient(), "bkt")
    from vmn_exp.storage.azure import AzureObjectClient

    return AzureObjectClient(FakeContainerClient("bkt"), MatchConditions.IfNotModified)


def _write(raw, path, live=False):
    write_v1(raw.put, lambda loc, rec: object_key(loc, rec, path), v1_records(live))


@pytest.mark.parametrize("path", ["team", None])
def test_s3_store_migrates(s3, path):
    _write(s3, path)
    uri = f"s3://bkt/{path}" if path else "s3://bkt"
    assert run_migrate(["--store", uri]) == 0
    root = path or "vmn"
    assert s3.keys() == {f"{root}/{k}" for k in expected_v2_keys(v1_records())} | {
        f"{root}/store.yml"}
    marker = yaml.safe_load(s3.get(f"{root}/store.yml"))
    assert marker["layout"] == 2 and "migrating" not in marker
    assert log_paths(s3, f"{root}/runs/my-app/r1/log/w1.jsonl")[1] == (
        "outputs/media/img/1.png")


def test_s3_shared_prefix_tells_runs_from_snapshots(s3):
    _write(s3, "team")
    assert run_migrate(["--store", "s3://bkt/team"]) == 0
    assert "team/snapshots/my-app/s1/metadata.yml" in s3.keys()
    assert "team/runs/my-app/r1/metadata.yml" in s3.keys()


def test_s3_idempotent_and_dry_run(s3):
    _write(s3, "team")
    before = {k: s3.get(k) for k in s3.keys()}
    assert run_migrate(["--store", "s3://bkt/team", "--dry-run"]) == 0
    assert {k: s3.get(k) for k in s3.keys()} == before
    assert run_migrate(["--store", "s3://bkt/team"]) == 0
    after = {k: s3.get(k) for k in s3.keys()}
    assert run_migrate(["--store", "s3://bkt/team"]) == 0
    assert {k: s3.get(k) for k in s3.keys()} == after


def test_s3_live_runs_stop_unless_skip_live(s3):
    _write(s3, "team", live=True)
    assert run_migrate(["--store", "s3://bkt/team"]) == 1
    assert "team/store.yml" not in s3.keys()
    assert run_migrate(["--store", "s3://bkt/team", "--skip-live"]) == 0
    assert "team/my-app/r2/metadata.yml" in s3.keys()
    assert "team/runs/my-app/r1/metadata.yml" in s3.keys()


@pytest.mark.parametrize("kind", ["gs", "az"])
def test_gcs_and_azure_stores_migrate(kind):
    raw = ObjectRaw(_client(kind), "bkt")
    _write(raw, "team")
    assert migrate_objects(raw.client, "bkt", "team") == 0
    assert raw.keys() == {f"team/{k}" for k in expected_v2_keys(v1_records())} | {
        "team/store.yml"}
    assert migrate_objects(raw.client, "bkt", "team") == 0
