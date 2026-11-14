"""A contract subset of the store's S3 records against moto: the real boto3
client (``s3_client.boto3_client``) and S3's own error codes."""
import pytest

pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from version_stamp.store.code import CODE_MISSING  # noqa: E402
from version_stamp.store.s3_client import boto3_client  # noqa: E402
from version_stamp.store.s3_store import open_s3_store  # noqa: E402

BUCKET = "vmn-store-bucket"
PATCHES = {"working_tree": "diff\n", "untracked_files": b"tar" * 10,
           "deps": {"dep_a": {"local_commits": "commits\n"}}}


def meta(verstr, **extra):
    return dict(verstr=verstr, timestamp="2026-01-01T00:00:00", **extra)


@pytest.fixture
def store(monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    with moto.mock_aws():
        boto3_client(None).create_bucket(Bucket=BUCKET)
        yield open_s3_store(f"s3://{BUCKET}/team", "snapshots", boto3_client)


def _keys(store):
    listed = store._s3.list_objects_v2(Bucket=BUCKET, Prefix="")
    return sorted(o["Key"] for o in listed.get("Contents", []))


def test_save_load_round_trip(store):
    store.save("root/svc", "v+1", meta("v+1"), PATCHES)
    metadata, patches = store.load_record("root/svc", "v+1")
    assert metadata["format_version"] == 1 and patches == PATCHES
    assert "team/snapshots/root-svc/v_plus_1/metadata.yml" in _keys(store)


def test_create_exclusive_claims(store):
    assert store.create_exclusive("app", "v", meta("v"), {}, claim_token="mine")
    assert not store.create_exclusive("app", "v", meta("v"), {}, claim_token="other")
    store._put("team/snapshots/app/w/.claim", b"theirs")
    assert not store.create_exclusive("app", "w", meta("w"), {}, claim_token="mine")


def test_update_metadata_and_a_missing_record(store):
    store.save("app", "v", meta("v"), {})
    assert store.update_note("app", "v", "hello")
    assert store.load_metadata("app", "v")["note"] == "hello"
    assert store.update_note("app", "nope", "x") is False


def test_list_and_delete(store):
    store.save("app", "b", dict(verstr="b", timestamp="2"), PATCHES)
    store.save("app", "a", dict(verstr="a", timestamp="1"), {})
    assert [m["verstr"] for m in store.list_snapshots("app")] == ["a", "b"]
    store.delete("app", "b")
    assert sorted(store.list_verstrs("app")) == ["a"]
    assert _keys(store) == ["team/snapshots/app/a/metadata.yml"]


def test_load_resolves_code_in_the_code_area(store):
    store.code_store.save("app", "c.1", meta("c.1"), {"working_tree": "code\n"})
    store.save("app", "v", meta("v", code="c.1"), {})
    store.save("app", "w", meta("w", code="gone"), {})
    assert store.load("app", "v")[1] == {"working_tree": "code\n"}
    assert store.load("app", "w")[0][CODE_MISSING] is True
