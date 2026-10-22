"""Child markers: an empty ``children/<child verstr>`` object inside the
parent's record, so a parent's children are one listing away — not a listing
of every record's ``parent`` field."""
import os

import pytest
from s3_helpers import mocked_bucket, raw_keys, record_calls, op_counts, s3_storage

from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "my_app"
PARENT = "0.0.1-dev.abc.def"
KIDS = [f"{PARENT}.r{i}" for i in range(2, 5)]


def _meta(verstr, **kw):
    return dict({"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, **kw)


@pytest.fixture
def local(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "root"), area="runs")
    storage.save(APP, PARENT, _meta(PARENT), {})
    return storage


@pytest.fixture
def s3(monkeypatch):
    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        storage.save(APP, PARENT, _meta(PARENT), {})
        yield storage


@pytest.fixture(params=["local", "s3"])
def store(request):
    return request.getfixturevalue(request.param)


def test_marked_children_list_back(store):
    for kid in KIDS:
        store.mark_child(APP, PARENT, kid)

    assert sorted(store.list_children(APP, PARENT)) == sorted(KIDS)


def test_a_record_without_children_lists_none(store):
    assert store.list_children(APP, PARENT) == []
    assert store.list_children(APP, "0.0.9-dev.nope") == []


def test_unmark_removes_one_marker_and_tolerates_a_missing_one(store):
    for kid in KIDS:
        store.mark_child(APP, PARENT, kid)

    store.unmark_child(APP, PARENT, KIDS[0])
    store.unmark_child(APP, PARENT, KIDS[0])
    store.unmark_child(APP, "0.0.9-dev.nope", KIDS[0])

    assert sorted(store.list_children(APP, PARENT)) == sorted(KIDS[1:])


def test_a_plus_in_the_child_name_round_trips(store):
    kid = PARENT + "+build"
    store.mark_child(APP, PARENT, kid)

    assert store.list_children(APP, PARENT) == [kid]


def test_markers_are_not_record_files(store):
    before = store.record_files(APP, PARENT)
    store.mark_child(APP, PARENT, KIDS[0])

    assert store.record_files(APP, PARENT).keys() == before.keys()
    assert store.list_files(APP)[PARENT].keys() == before.keys()
    assert store.list_artifacts(APP, PARENT) == []


def test_markers_never_count_as_records(store):
    store.mark_child(APP, PARENT, KIDS[0])

    assert store.list_verstrs(APP) == [PARENT]
    assert [m["verstr"] for m in store.list_snapshots(APP)] == [PARENT]


def test_deleting_the_parent_drops_its_markers(store):
    store.mark_child(APP, PARENT, KIDS[0])
    store.delete(APP, PARENT)

    assert store.list_children(APP, PARENT) == []


def test_local_marker_of_a_missing_parent_writes_nothing(local, tmp_path):
    local.mark_child(APP, "0.0.9-dev.nope", KIDS[0])

    assert not os.path.exists(local._snapshot_dir(APP, "0.0.9-dev.nope"))


def test_local_later_children_leave_the_record_signature_alone(local):
    local.mark_child(APP, PARENT, KIDS[0])
    sig = local.list_record_names(APP)[PARENT]

    local.mark_child(APP, PARENT, KIDS[1])
    local.unmark_child(APP, PARENT, KIDS[1])

    assert local.list_record_names(APP)[PARENT] == sig


def test_s3_marker_is_one_put_and_listing_is_one_list(s3):
    calls = record_calls(s3._s3)
    s3.mark_child(APP, PARENT, KIDS[0])
    assert op_counts(calls) == {"PutObject": 1}

    calls.clear()
    s3.list_children(APP, PARENT)
    assert op_counts(calls) == {"ListObjectsV2": 1}
    assert f"exps/runs/{APP}/{PARENT}/children/{KIDS[0]}" in raw_keys()


def test_s3_record_listing_skips_the_children_subtree(s3):
    for kid in KIDS:
        s3.mark_child(APP, PARENT, kid)
    calls = record_calls(s3._s3)

    files = s3.list_files(APP, keys=[PARENT])[PARENT]

    assert not any(name.startswith("children/") for name in files)
    # The delimited record listing never pages through the markers.
    assert op_counts(calls)["ListObjectsV2"] == 3


@pytest.fixture
def cached(tmp_path, monkeypatch):
    with mocked_bucket(monkeypatch):
        remote = s3_storage()
        storage = CachedSnapshotStorage(
            LocalSnapshotStorage(str(tmp_path / "root"), area="runs"), remote
        )
        storage.create_exclusive(APP, PARENT, _meta(PARENT), {})
        yield storage, remote


def test_cached_marks_both_copies(cached):
    storage, remote = cached
    storage.mark_child(APP, PARENT, KIDS[0])

    assert storage._local.list_children(APP, PARENT) == [KIDS[0]]
    assert remote.list_children(APP, PARENT) == [KIDS[0]]
    assert storage.list_children(APP, PARENT) == [KIDS[0]]


def test_cached_lists_the_union_of_both_copies(cached):
    storage, remote = cached
    remote.mark_child(APP, PARENT, KIDS[0])
    storage._local.mark_child(APP, PARENT, KIDS[1])

    assert sorted(storage.list_children(APP, PARENT)) == sorted(KIDS[:2])


def test_cached_marks_a_remote_only_parent_on_the_remote(cached):
    storage, remote = cached
    other = "0.0.2-dev.abc.def"
    remote.save(APP, other, _meta(other), {})

    storage.mark_child(APP, other, KIDS[0])

    assert remote.list_children(APP, other) == [KIDS[0]]


def test_cached_unmark_removes_both(cached):
    storage, remote = cached
    storage.mark_child(APP, PARENT, KIDS[0])
    storage.unmark_child(APP, PARENT, KIDS[0])

    assert storage.list_children(APP, PARENT) == []
    assert remote.list_children(APP, PARENT) == []
