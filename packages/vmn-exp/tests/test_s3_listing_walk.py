"""Listing the files of many consecutive records at once: a walk of their
key range, about one LIST per 1000 objects, instead of three delimited LISTs
per record (the record, log/, metrics/) — at 497k runs that was ~1.5M LISTs
and over an hour before a cold index published anything. Record names come
a page at a time, so a listing can start on the first page."""
import pytest
from s3_helpers import meta, mocked_bucket, record_calls, s3_storage


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def _seed(s3, tmp_path):
    art = tmp_path / "model.pt"
    art.write_bytes(b"x")
    names = ["0.1", "0.1.r2", "0.1-b", "0.2", "0.3", "0.30", "1.0"]
    for i, v in enumerate(names):
        s3.save("app", v, meta(v), {"deps": {"dep": {"working_tree": "d"}}} if i % 2 else {})
        s3.append_log_entry("app", v, "w", {"timestamp": "t", "type": "note"})
        s3.save_file("app", v, "run_state.yml", "state: running\n")
        if i % 3 == 0:
            s3.save_artifact_file("app", v, str(art))
    return sorted(s3.list_record_names("app"))


def _lists(calls):
    return [p for op, p in calls if op == "ListObjectsV2"]


def test_a_range_walk_lists_what_listing_each_record_does(tmp_path):
    s3 = s3_storage()
    names = _seed(s3, tmp_path)
    keyed = s3.list_files("app", keys=names)
    calls = record_calls(s3._s3)

    walked = s3.list_files_between("app", names)

    assert walked == keyed
    assert len(_lists(calls)) == 1


def test_a_range_walk_lists_only_the_names_asked_for(tmp_path):
    s3 = s3_storage()
    names = _seed(s3, tmp_path)
    inner = [n for n in names if n not in (names[0], names[-1], "0.2")]

    walked = s3.list_files_between("app", inner)

    assert set(walked) == set(inner)
    assert walked == s3.list_files("app", keys=inner)


def test_a_range_walk_pages_and_jumps_past_subtrees(tmp_path, monkeypatch):
    s3 = s3_storage()
    names = _seed(s3, tmp_path)
    for i in range(30):  # a big artifacts subtree in the middle
        s3._put(f"{s3._record_prefix('app', '0.2')}/artifacts/f{i:03d}", b"x")
    keyed = s3.list_files("app", keys=names)
    real = s3._s3.list_objects_v2

    def small_pages(**params):
        return real(**dict(params, MaxKeys=5))

    monkeypatch.setattr(s3._s3, "list_objects_v2", small_pages)
    assert s3.list_files_between("app", names) == keyed


def test_record_names_come_a_page_at_a_time(tmp_path, monkeypatch):
    s3 = s3_storage()
    names = _seed(s3, tmp_path)
    real = s3._s3.list_objects_v2
    monkeypatch.setattr(s3._s3, "list_objects_v2", lambda **p: real(**dict(p, MaxKeys=3)))

    pages = list(s3.record_name_pages("app"))

    assert [len(p) for p in pages] == [3, 3, 1]
    in_store_order = sorted(names, key=lambda n: f"{n}/")  # "0.1-b/" < "0.1.r2/" < "0.1/"
    assert [n for page in pages for n in page] == in_store_order
