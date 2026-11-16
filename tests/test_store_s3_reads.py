"""S3 record reads of ``version_stamp.store`` against an in-memory client."""
import pytest

from s3_fakes import FakeS3Client, FakeS3Error
from version_stamp.store.code import CODE_MISSING
from version_stamp.store.s3_reads import read_patches, read_record
from version_stamp.store.s3_store import S3RecordStore

BUCKET = "bkt"
PREFIX = "team/snapshots"
PATCHES = {"working_tree": "diff\n", "untracked_files": b"tar" * 10,
           "deps": {"dep_a": {"local_commits": "commits\n"}, "dep_b": {"working_tree": "b\n"}}}


def meta(verstr, **extra):
    return dict(verstr=verstr, timestamp="2026-01-01T00:00:00", **extra)


@pytest.fixture
def client():
    return FakeS3Client()


@pytest.fixture
def store(client):
    return S3RecordStore(BUCKET, PREFIX, client)


def test_load_record_round_trips_patches_and_deps(store):
    store.save("app", "v+1", meta("v+1"), PATCHES)
    metadata, patches = store.load_record("app", "v+1")
    assert metadata["verstr"] == "v+1" and metadata["format_version"] == 1
    assert patches == PATCHES


def test_load_record_of_a_missing_record(store):
    assert store.load_record("app", "v") == (None, None)


def test_read_record_of_a_code_reference_reads_no_patch_files(store, client):
    store.save("app", "v", meta("v", code="c.1"), {"working_tree": "ignored"})
    client.calls.clear()
    metadata, patches = read_record(store, store._record_prefix("app", "v"))
    assert metadata["code"] == "c.1" and patches == {}
    assert [op for op, _ in client.calls] == ["get_object"]


def test_read_patches_reads_a_prefix(store):
    store.save("app", "v", meta("v"), PATCHES)
    assert read_patches(store, store._record_prefix("app", "v")) == PATCHES


def test_read_record_redacts_remotes(store, client):
    client.objects[(BUCKET, f"{PREFIX}/app/v/metadata.yml")] = (
        b"verstr: v\nremote: https://u:p@host/x\n")
    assert store.load_record("app", "v")[0]["remote"] == "https://host/x"


def test_load_resolves_a_code_reference_through_the_code_store(client):
    code = S3RecordStore(BUCKET, "team/code", client)
    code.save("app", "c.1", meta("c.1"), {"working_tree": "code diff\n"})
    store = S3RecordStore(BUCKET, PREFIX, client, code_store=code)
    store.save("app", "v", meta("v", code="c.1"), {})
    metadata, patches = store.load("app", "v")
    assert patches == {"working_tree": "code diff\n"} and CODE_MISSING not in metadata


def test_load_marks_a_missing_code_object(store):
    store.save("app", "v", meta("v", code="gone"), {})
    metadata, patches = store.load("app", "v")
    assert metadata[CODE_MISSING] is True and patches == {}


def test_a_store_is_its_own_code_store_by_default(store):
    assert store.code_store is store


def test_exists(store):
    store.save("app", "v", meta("v"), {})
    assert store.exists("app", "v")
    assert not store.exists("app", "w")
    assert not store.exists("app", "../x")


def test_load_file_and_metadata(store, client):
    store.save("app", "v", meta("v"), {"working_tree": "d"})
    assert store.load_file("app", "v", "working_tree.patch") == b"d"
    assert store.load_file("app", "v", "nope") is None
    assert store.load_metadata("app", "v")["verstr"] == "v"
    assert store.load_metadata("app", "w") is None


def test_load_metadata_of_a_verinfo_file_is_none(store, client):
    client.objects[(BUCKET, f"{PREFIX}/app/v/metadata.yml")] = b"vmn_info: {}\n"
    assert store.load_metadata("app", "v") is None


def test_listing_pages_through_every_record_by_delimiter(store, client):
    for v in ("a", "b+1", "c", "d", "e"):
        store.save("app", v, meta(v), PATCHES)
    client.calls.clear()
    assert sorted(store.list_verstrs("app")) == ["a", "b+1", "c", "d", "e"]
    listings = client.ops("list_objects_v2")
    assert len(listings) == 3 and all(kw["Delimiter"] == "/" for kw in listings)
    assert sorted(store.list_record_names("app")) == ["a", "b+1", "c", "d", "e"]


def test_listing_an_unknown_app_is_empty(store):
    assert store.list_verstrs("app") == [] and store.list_snapshots("app") == []


def test_list_snapshots_sorted_by_timestamp_skipping_unparsable(store, client):
    store.save("app", "late", dict(verstr="late", timestamp="2026-03"), {})
    store.save("app", "early", dict(verstr="early", timestamp="2026-01"), {})
    store.save("app", "mid", dict(verstr="mid", timestamp="2026-02"), {})
    client.objects[(BUCKET, f"{PREFIX}/app/bad/metadata.yml")] = b": : [\n"
    client.objects[(BUCKET, f"{PREFIX}/app/claimed/.claim")] = b""
    assert [m["verstr"] for m in store.list_snapshots("app")] == ["early", "mid", "late"]


def test_list_snapshots_raises_on_a_failed_read(store, client):
    store.save("app", "v", meta("v"), {})

    def refuse(**kwargs):
        raise FakeS3Error("AccessDenied")

    client.get_object = refuse
    with pytest.raises(FakeS3Error):
        store.list_snapshots("app")


def _refusing(client, op, code="ExpiredToken"):
    def refuse(**kwargs):
        raise FakeS3Error(code)

    setattr(client, op, refuse)


@pytest.mark.parametrize("filename", ["metadata.yml", "working_tree.patch"])
def test_load_raises_on_a_failed_read_not_a_missing_record(store, client, filename):
    """A record whose metadata or patch can't be read is no missing record
    (``Snapshot not found``) and no record with fewer patches."""
    store.save("app", "v", meta("v"), {"working_tree": "diff\n"})
    real_get = client.get_object

    def refuse_one(Bucket, Key, Range=None):
        if Key.endswith(filename):
            raise FakeS3Error("ExpiredToken")
        return real_get(Bucket=Bucket, Key=Key, Range=Range)

    client.get_object = refuse_one
    with pytest.raises(FakeS3Error):
        store.load("app", "v")


def test_load_file_raises_on_a_failed_read(store, client):
    store.save("app", "v", meta("v"), {"working_tree": "diff\n"})
    _refusing(client, "get_object")
    with pytest.raises(FakeS3Error):
        store.load_file("app", "v", "working_tree.patch")


@pytest.mark.parametrize("op", ["get_object", "list_objects_v2"])
def test_load_raises_on_a_failed_dep_read(store, client, op):
    """A dep patch that can't be read or listed is no record without dep patches."""
    store.save("app", "v", meta("v"), PATCHES)
    real = getattr(client, op)

    def refuse_deps(**kwargs):
        if "/deps/" in (kwargs.get("Key") or kwargs.get("Prefix") or ""):
            raise FakeS3Error("ExpiredToken")
        return real(**kwargs)

    setattr(client, op, refuse_deps)
    with pytest.raises(FakeS3Error):
        store.load("app", "v")


def test_exists_raises_on_a_failed_head(store, client):
    _refusing(client, "head_object")
    with pytest.raises(FakeS3Error):
        store.exists("app", "v")
