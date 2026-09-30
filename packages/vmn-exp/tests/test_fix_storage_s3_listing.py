"""S3 listings at 10k+ runs: names by delimiter, files per record, legacy keys merged."""
import pytest
from s3_helpers import (
    PREFIX,
    concurrently,
    meta,
    mocked_bucket,
    put_raw,
    record_calls,
    s3_storage,
)


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def _seed_with_bulk(s3, verstr, tmp_path):
    s3.save("app", verstr, meta(verstr), {"deps": {"dep": {"working_tree": "d"}}})
    s3.append_log_entry("app", verstr, "w", {"timestamp": "t", "type": "note"})
    art = tmp_path / "model.pt"
    art.write_bytes(b"x")
    s3.save_artifact_file("app", verstr, str(art))


def test_list_record_names_lists_by_delimiter(tmp_path):
    s3 = s3_storage()
    for v in ("v1", "v2", "v3"):
        _seed_with_bulk(s3, v, tmp_path)
    calls = record_calls(s3._s3)

    assert s3.list_record_names("app") == {"v1": None, "v2": None, "v3": None}
    lists = [p for op, p in calls if op == "ListObjectsV2"]
    assert lists and all(p.get("Delimiter") == "/" for p in lists)


def test_list_files_for_keys_lists_only_those_records(tmp_path):
    s3 = s3_storage()
    for v in ("v1", "v2", "v3"):
        _seed_with_bulk(s3, v, tmp_path)
    calls = record_calls(s3._s3)

    files = s3.list_files("app", keys=["v1", "v3"])

    assert set(files) == {"v1", "v3"}
    assert {"metadata.yml", "log.w.jsonl"} <= set(files["v1"])
    assert not any("/" in name for names in files.values() for name in names)
    prefixes = sorted(p["Prefix"] for op, p in calls if op == "ListObjectsV2")
    assert prefixes == [f"{PREFIX}/app/v1/", f"{PREFIX}/app/v3/"]
    assert all(p.get("Delimiter") == "/" for op, p in calls if op == "ListObjectsV2")


def test_list_files_for_keys_skips_unknown_records():
    s3 = s3_storage()
    s3.save("app", "v1", meta("v1"), {})
    assert set(s3.list_files("app", keys=["v1", "gone"])) == {"v1"}


def test_list_files_for_keys_lists_records_concurrently():
    s3 = s3_storage()
    for v in ("v1", "v2"):
        s3.save("app", v, meta(v), {})
    s3._s3.list_objects_v2 = concurrently(2, s3._s3.list_objects_v2)
    assert set(s3.list_files("app", keys=["v1", "v2"])) == {"v1", "v2"}


def test_list_files_leaves_out_claim_markers():
    s3 = s3_storage()
    assert s3.create_exclusive("app", "v1", meta("v1"), {})
    assert set(s3.list_files("app")["v1"]) == {"metadata.yml"}
    assert set(s3.list_files("app", keys=["v1"])["v1"]) == {"metadata.yml"}


def test_list_run_verstrs_lists_only_that_codes_own_runs():
    s3 = s3_storage()
    s3.save("app", "0.0.1", meta("0.0.1"), {})
    s3.save("app", "0.0.1.r2", meta("0.0.1.r2"), {})
    # A different code_verstr that merely shares "0.0.1" as a string prefix.
    s3.save("app", "0.0.10", meta("0.0.10"), {})
    calls = record_calls(s3._s3)

    names = s3.list_run_verstrs("app", "0.0.1")

    assert names == {"0.0.1", "0.0.1.r2"}
    prefixes = [p.get("Prefix") for op, p in calls if op == "ListObjectsV2"]
    assert prefixes and all(p == f"{PREFIX}/app/0.0.1." for p in prefixes)


def test_list_run_verstrs_is_empty_for_an_unstamped_code_verstr():
    s3 = s3_storage()
    s3.save("app", "0.0.1", meta("0.0.1"), {})

    assert s3.list_run_verstrs("app", "9.9.9") == set()


LEGACY_META = b"verstr: old\napp_name: root/svc\ntimestamp: '2025-01-01T00:00:00Z'\n"


def _with_legacy_and_new():
    put_raw(f"{PREFIX}/root_svc/old/metadata.yml", LEGACY_META)
    s3 = s3_storage()
    s3.save("root/svc", "new", meta("new"), {})
    return s3


def test_legacy_records_stay_visible_next_to_new_ones():
    s3 = _with_legacy_and_new()
    assert [m["verstr"] for m in s3.list_snapshots("root/svc")] == ["old", "new"]
    assert sorted(s3.list_verstrs("root/svc")) == ["new", "old"]
    assert s3.list_record_names("root/svc") == {"new": None, "old": None}
    assert set(s3.list_files("root/svc")) == {"new", "old"}
    assert set(s3.list_files("root/svc", keys=["old", "new"])) == {"new", "old"}


def test_another_apps_records_under_the_shared_legacy_key_stay_hidden():
    s3 = _with_legacy_and_new()
    put_raw(f"{PREFIX}/root_svc/theirs/metadata.yml", b"verstr: theirs\napp_name: root_svc\n")
    assert s3.list_record_names("root/svc") == {"new": None, "old": None}
    assert set(s3.list_files("root/svc")) == {"new", "old"}
    assert set(s3.list_files("root/svc", keys=["theirs", "old"])) == {"old"}


def test_a_record_under_both_keys_is_listed_once_from_the_new_key():
    put_raw(f"{PREFIX}/root_svc/v/metadata.yml", b"verstr: v\ntimestamp: old\n")
    s3 = s3_storage()
    s3.save("root/svc", "v", meta("v", timestamp="new"), {})
    snaps = s3.list_snapshots("root/svc")
    assert [(m["verstr"], m["timestamp"]) for m in snaps] == [("v", "new")]


def test_the_legacy_probe_is_not_repeated_every_listing():
    s3 = s3_storage()
    s3.save("root/svc", "new", meta("new"), {})
    s3.list_files("root/svc")
    calls = record_calls(s3._s3)
    s3.list_files("root/svc")
    assert [op for op, _ in calls] == ["ListObjectsV2"]


def test_full_listing_skips_a_records_heavy_subtree_spanning_pages(tmp_path):
    """A full ``list_files()`` (no keys — the periodic full sweep) must not
    page through a whole record's ``artifacts/`` tree object by object: once
    a page ends inside it, the next request jumps straight past it."""
    s3 = s3_storage()
    s3.save("app", "v1", meta("v1"), {})
    for name in "abcdef":
        art = tmp_path / f"{name}.bin"
        art.write_bytes(b"x")
        s3.save_artifact_file("app", "v1", str(art))
    real_list = s3._s3.list_objects_v2
    s3._s3.list_objects_v2 = lambda **kw: real_list(**dict(kw, MaxKeys=2))
    calls = record_calls(s3._s3)

    files = s3.list_files("app")

    assert set(files["v1"]) == {"metadata.yml"}
    lists = [p for op, p in calls if op == "ListObjectsV2"]
    # Without the fix this pages through all 6 artifacts + metadata.yml two
    # at a time (4 calls); the fix jumps past the artifacts/ subtree in one.
    assert len(lists) == 2
    assert lists[1].get("StartAfter", "").endswith("/v1/artifacts0")
