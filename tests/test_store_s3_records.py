"""S3 record writes of ``version_stamp.store`` against an in-memory client:
the key layout of plan 14, metadata.yml written last and deleted first,
claims, and the ETag compare-and-swap of a metadata update."""
import sys

import pytest
import yaml

from s3_fakes import FakeS3Client, FakeS3Error
from version_stamp.store import s3_base, s3_client, s3_records
from version_stamp.store.s3_store import S3RecordStore, open_s3_store

BUCKET = "bkt"
PREFIX = "team/snapshots"
PATCHES = {"working_tree": "diff\n", "untracked_files": b"tar" * 10,
           "deps": {"dep/a": {"local_commits": "commits\n"}}}


def meta(verstr, **extra):
    return dict(verstr=verstr, timestamp="2026-01-01T00:00:00", **extra)


@pytest.fixture
def client():
    return FakeS3Client()


@pytest.fixture
def store(client):
    return S3RecordStore(BUCKET, PREFIX, client)


def _put_keys(client):
    return [kw["Key"] for kw in client.ops("put_object")]


def _metadata(client, key):
    return yaml.safe_load(client.objects[(BUCKET, key)])


def test_a_record_lives_under_area_app_key_and_safe_verstr(store, client):
    store.save("root/svc", "0.0.1-dev.1+abc", meta("0.0.1-dev.1+abc"), PATCHES)
    base = "team/snapshots/root-svc/0.0.1-dev.1_plus_abc"
    assert client.keys(BUCKET) == [
        f"{base}/deps/dep_a/local_commits.patch",
        f"{base}/metadata.yml",
        f"{base}/untracked_files.tar.gz",
        f"{base}/working_tree.patch",
    ]


def test_save_writes_metadata_last(store, client):
    store.save("app", "v", meta("v"), PATCHES)
    assert _put_keys(client)[-1].endswith("/v/metadata.yml")
    assert len(_put_keys(client)) == 4


def test_metadata_is_stamped_format_1_unless_it_has_a_version(store, client):
    store.save("app", "v1", meta("v1"), {})
    store.save("app", "v2", meta("v2", format_version=2), {})
    assert _metadata(client, f"{PREFIX}/app/v1/metadata.yml")["format_version"] == 1
    assert _metadata(client, f"{PREFIX}/app/v2/metadata.yml")["format_version"] == 2


def test_metadata_carries_no_remote_credentials(store, client):
    store.save("app", "v", meta("v", remote="https://user:tok@host/x"), {})
    assert _metadata(client, f"{PREFIX}/app/v/metadata.yml")["remote"] == "https://host/x"


def test_create_exclusive_claims_then_writes_metadata_last(store, client):
    assert store.create_exclusive("app", "v", meta("v"), PATCHES)
    puts = client.ops("put_object")
    assert puts[0]["Key"].endswith("/v/.claim") and puts[0]["IfNoneMatch"] == "*"
    assert puts[-1]["Key"].endswith("/v/metadata.yml")


def test_create_exclusive_loses_to_an_existing_claim(store, client):
    client.objects[(BUCKET, f"{PREFIX}/app/v/.claim")] = b"other"
    assert not store.create_exclusive("app", "v", meta("v"), {}, claim_token="mine")
    assert not store.exists("app", "v")


def test_create_exclusive_loses_to_an_empty_claim_even_without_a_token(store, client):
    client.objects[(BUCKET, f"{PREFIX}/app/v/.claim")] = b""
    assert not store.create_exclusive("app", "v", meta("v"), {})


def test_create_exclusive_resumes_its_own_claim(store, client):
    client.objects[(BUCKET, f"{PREFIX}/app/v/.claim")] = b"mine"
    assert store.create_exclusive("app", "v", meta("v"), {}, claim_token="mine")
    assert store.exists("app", "v")


def test_create_exclusive_loses_to_existing_metadata(store, client):
    store.save("app", "v", meta("v"), {})
    assert not store.create_exclusive("app", "v", meta("v"), {})


def test_delete_removes_metadata_first_then_everything(store, client):
    assert store.create_exclusive("app", "v", meta("v"), PATCHES)
    store.save("app", "w", meta("w"), {})
    client.calls.clear()
    store.delete("app", "v")
    deletes = [(op, kw) for op, kw in client.calls if op.startswith("delete")]
    assert deletes[0] == ("delete_object", {"Bucket": BUCKET, "Key": f"{PREFIX}/app/v/metadata.yml"})
    assert client.keys(BUCKET) == [f"{PREFIX}/app/w/metadata.yml"]


def test_delete_batches_keys(store, client, monkeypatch):
    monkeypatch.setattr(s3_records, "DELETE_BATCH", 2)
    store.save("app", "v", meta("v"), PATCHES)
    store.delete("app", "v")
    assert [len(kw["Delete"]["Objects"]) for kw in client.ops("delete_objects")] == [2, 1]
    assert client.keys(BUCKET) == []


REFUSED = {"Key": f"{PREFIX}/app/v/working_tree.patch", "Code": "AccessDenied",
           "Message": "Access Denied"}


def test_a_refused_batch_delete_is_an_s3_client_error_with_the_same_message(store, client):
    """A key S3 refuses in a ``delete_objects`` batch: still a RuntimeError
    naming the keys and codes (SDK callers), classified as an S3 failure."""
    from version_stamp.store.s3_errors import is_client_error

    store.save("app", "v", meta("v"), {"working_tree": "diff\n"})
    client.delete_objects = lambda Bucket, Delete: {"Errors": [REFUSED]}
    with pytest.raises(RuntimeError) as exc:
        store.delete("app", "v")
    assert str(exc.value) == f"S3 refused to delete 1 objects: {REFUSED}"
    assert is_client_error(exc.value)


def test_update_metadata_merges_and_drops_fields(store, client):
    store.save("app", "v", meta("v", note="old", tag="x"), {})
    assert store.update_metadata("app", "v", {"note": "new", "tag": None})
    found = _metadata(client, f"{PREFIX}/app/v/metadata.yml")
    assert found["note"] == "new" and "tag" not in found
    assert client.ops("put_object")[-1]["IfMatch"]


def test_update_metadata_retries_on_a_concurrent_edit(store, client):
    store.save("app", "v", meta("v"), {})
    key = f"{PREFIX}/app/v/metadata.yml"

    def race_once(kwargs):
        if kwargs.get("IfMatch") and not race_once.done:
            race_once.done = True
            client.objects[(BUCKET, key)] = yaml.dump(meta("v", other="edit")).encode()

    race_once.done = False
    client.before_put = race_once
    assert store.update_note("app", "v", "hi")
    found = _metadata(client, key)
    assert found["note"] == "hi" and found["other"] == "edit"


def test_update_metadata_gives_up_after_too_many_writers(store, client):
    store.save("app", "v", meta("v"), {})

    def always_race(kwargs):
        if kwargs.get("IfMatch"):
            raise FakeS3Error("412")

    client.before_put = always_race
    with pytest.raises(RuntimeError, match="too many writers"):
        store.update_note("app", "v", "hi")
    assert len(client.ops("put_object")) == 1 + s3_records.UPDATE_ATTEMPTS


def test_update_metadata_of_a_missing_record_is_false(store):
    assert store.update_metadata("app", "nope", {"note": "x"}) is False


def test_open_area_shares_the_client(store, client):
    code = store._open_area("code")
    assert code.prefix == "team/code" and code.area == "code" and store.area == "snapshots"
    assert code._s3 is client


def test_map_keeps_order_with_bounded_workers(store):
    assert store._map(lambda x: x * 2, range(25)) == [x * 2 for x in range(25)]


def test_the_object_base_defines_no_record_api_names():
    record_api = ("exists", "load", "load_record", "load_metadata", "load_file", "save",
                  "delete", "create_exclusive")
    names = vars(s3_base.S3ObjectBase)
    assert [n for n in names if n in record_api or n.startswith(("list_", "update_"))] == []


def test_open_s3_store_parses_the_uri_and_builds_one_client():
    built = []

    def factory(endpoint_url):
        built.append(endpoint_url)
        return FakeS3Client()

    store = open_s3_store("s3://bkt/team?endpoint_url=http://minio:9000", "snapshots", factory)
    assert (store.bucket, store.prefix, store.endpoint_url) == ("bkt", "team/snapshots", "http://minio:9000")
    assert built == ["http://minio:9000"]
    assert store.code_store.prefix == "team/code" and store.code_store._s3 is store._s3


def test_open_s3_store_without_a_path_uses_the_default_root():
    store = open_s3_store("s3://bkt", "snapshots", lambda endpoint_url: FakeS3Client())
    assert store.prefix == "vmn/snapshots" and store.endpoint_url is None


def test_open_s3_store_refuses_another_scheme():
    with pytest.raises(ValueError):
        open_s3_store("gs://bkt/x", "snapshots", lambda endpoint_url: FakeS3Client())


def test_client_settings_match_the_sdk():
    assert (s3_client.CONNECT_TIMEOUT_SEC, s3_client.READ_TIMEOUT_SEC) == (10, 30)
    assert s3_client.RETRIES == {"mode": "adaptive", "total_max_attempts": 5}
    assert s3_client.MAX_POOL_CONNECTIONS == 320


def test_missing_boto3_names_the_s3_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    with pytest.raises(ImportError, match=r"pip install 'vmn\[s3\]'"):
        s3_client.boto3_module()
