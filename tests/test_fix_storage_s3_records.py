"""S3 record lifecycle: metadata.yml is written last and deleted first, and a
note edit touches only metadata.yml under an ETag precondition."""
import pytest
from s3_helpers import (
    PREFIX,
    concurrently,
    meta,
    mocked_bucket,
    put_raw,
    raw_keys,
    record_calls,
    s3_storage,
)

PATCHES = {"working_tree": "diff", "untracked_files": b"tar" * 100}


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def _puts(calls):
    return [p["Key"].rsplit("/", 1)[1] for op, p in calls if op == "PutObject"]


def test_create_claims_with_a_marker_and_writes_metadata_last():
    s3 = s3_storage()
    calls = record_calls(s3._s3)
    assert s3.create_exclusive("app", "v", meta("v"), PATCHES)
    puts = _puts(calls)
    assert puts[0] == ".claim" and puts[-1] == "metadata.yml"
    assert {"working_tree.patch", "untracked_files.tar.gz"} <= set(puts)
    claim = next(p for op, p in calls if op == "PutObject")
    assert claim.get("IfNoneMatch") == "*"


def test_a_claimed_name_without_metadata_is_invisible_but_taken():
    s3 = s3_storage()
    put_raw(f"{PREFIX}/app/v/.claim", b"")
    assert not s3.exists("app", "v")
    assert s3.list_snapshots("app") == []
    assert not s3.create_exclusive("app", "v", meta("v"), {})


def test_a_record_created_before_claims_existed_still_blocks_the_name():
    put_raw(f"{PREFIX}/app/v/metadata.yml", b"verstr: v\ntimestamp: t\n")
    assert not s3_storage().create_exclusive("app", "v", meta("v"), {})


def test_delete_removes_metadata_first():
    s3 = s3_storage()
    s3.save("app", "v", meta("v"), PATCHES)
    calls = record_calls(s3._s3)
    s3.delete("app", "v")
    first = next(p for op, p in calls if op in ("DeleteObject", "DeleteObjects"))
    assert first.get("Key", "").endswith("/metadata.yml")
    assert raw_keys() == []


def test_delete_clears_the_claim_marker_too():
    s3 = s3_storage()
    assert s3.create_exclusive("app", "v", meta("v"), PATCHES)
    s3.delete("app", "v")
    assert raw_keys() == []


def test_delete_removes_large_records_in_concurrent_batches(monkeypatch):
    import version_stamp.cli.snapshot_storage_s3_records as records

    monkeypatch.setattr(records, "_DELETE_BATCH", 2)
    s3 = s3_storage()
    s3.save("app", "v", meta("v"), PATCHES)
    for i in range(1, 4):
        s3.save_file("app", "v", f"log.w@{i:06d}.jsonl", "{}\n")
    s3._s3.delete_objects = concurrently(2, s3._s3.delete_objects)
    s3.delete("app", "v")
    assert raw_keys() == []


def test_update_note_touches_only_metadata_with_a_precondition():
    s3 = s3_storage()
    s3.save("app", "v", meta("v", note="old"), PATCHES)
    calls = record_calls(s3._s3)
    assert s3.update_note("app", "v", "new")
    touched = {p["Key"].rsplit("/", 1)[1] for op, p in calls if "Key" in p}
    assert touched == {"metadata.yml"}
    put = next(p for op, p in calls if op == "PutObject")
    assert put.get("IfMatch")
    assert s3.load("app", "v")[0]["note"] == "new"
    assert s3.load("app", "v")[1]["untracked_files"] == PATCHES["untracked_files"]


def test_update_note_retries_when_metadata_changes_underneath():
    s3, other = s3_storage(), s3_storage()
    s3.save("app", "v", meta("v"), {})
    real_get = s3._s3.get_object
    raced = []

    def get_then_race(**kwargs):
        resp = real_get(**kwargs)
        if not raced:
            raced.append(True)
            other.save("app", "v", meta("v", extra="kept"), {})
        return resp

    s3._s3.get_object = get_then_race
    assert s3.update_note("app", "v", "n")
    loaded = s3.load("app", "v")[0]
    assert loaded["note"] == "n" and loaded["extra"] == "kept"


def test_update_note_of_a_missing_record_is_false():
    assert not s3_storage().update_note("app", "nope", "n")
