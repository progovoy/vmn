"""Reading only the text patches of a run's code — never its untracked
tarball — for the features its code says about it (``vmn-exp similar-backfill``).
"""
from version_stamp.snapshot import code_store as vmn_code
from version_stamp.snapshot.local_store import LocalRecordStore
from vmn_exp.core.code_patches import code_patch_texts, patch_items, record_patch_texts
from vmn_exp.core.code_store import code_storage, store_code
from vmn_exp.storage.areas import local_store_root
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "root_app/svc"
KEY = "0.0.1-dev.abc1234.0000001.ffff"
WT = "diff --git a/src/loss.py b/src/loss.py\n+x\n"
LC = "From 0123 Mon Sep 17 00:00:00 2001\nFrom: A <a@x.io>\nSubject: [PATCH] one\n"
DEP_WT = "diff --git a/lib.py b/lib.py\n+y\n"
PAYLOAD = {
    "working_tree": WT,
    "local_commits": LC,
    "untracked_files": b"\x1f\x8bTAR",
    "deps": {"../dep": {"working_tree": DEP_WT, "untracked_files": b"\x1f\x8bTAR"}},
}
SUMMARY = {"has_working_tree_patch": True, "has_local_commits_patch": True,
           "has_untracked_files": True, "has_dep_patches": True}


def _storage(root):
    return LocalSnapshotStorage(local_store_root(str(root)), area="runs")


def _spy_reads(storage):
    """The file names read from *storage*; reading a whole record fails."""
    read = []
    original = storage.load_file

    def load_file(app_name, verstr, filename):
        read.append(filename)
        return original(app_name, verstr, filename)

    def load_record(*args, **kwargs):
        raise AssertionError("read the whole record, untracked tarball included")

    storage.load_file = load_file
    storage.load_record = load_record
    return read


def test_a_code_objects_text_patches_and_its_deps_without_the_tarball(tmp_path):
    storage = _storage(tmp_path)
    store_code(storage, APP, KEY, PAYLOAD, SUMMARY)
    read = _spy_reads(code_storage(storage))

    assert code_patch_texts(storage, APP, KEY, dep_paths=["../dep", "../clean"]) == {
        "working_tree": WT,
        "local_commits": LC,
        "deps": {"../dep": {"working_tree": DEP_WT}},
    }
    assert read and not [name for name in read if name.endswith(".tar.gz")]


def test_a_missing_or_incomplete_code_object_has_no_patches(tmp_path):
    storage = _storage(tmp_path)
    assert code_patch_texts(storage, APP, KEY) is None

    code_storage(storage).save(APP, KEY, {"verstr": KEY}, {"working_tree": WT})
    marker = tmp_path / ".vmn" / "store" / "code" / "root_app-svc" / KEY / "metadata.yml"
    marker.unlink()
    assert code_patch_texts(storage, APP, KEY) is None


def test_a_code_object_vmn_wrote_reads_the_same(tmp_path):
    vmn_code.store_code(LocalRecordStore(str(tmp_path), "code"), APP, KEY, PAYLOAD, SUMMARY)

    patches = code_patch_texts(_storage(tmp_path), APP, KEY, dep_paths=["../dep"])

    assert patches == {"working_tree": WT, "local_commits": LC,
                       "deps": {"../dep": {"working_tree": DEP_WT}}}


def test_undecodable_patch_bytes_are_replaced_not_fatal(tmp_path):
    storage = _storage(tmp_path)
    store_code(storage, APP, KEY, {"working_tree": WT}, SUMMARY)
    path = tmp_path / ".vmn" / "store" / "code" / "root_app-svc" / KEY / "working_tree.patch"
    path.write_bytes(b"diff --git a/f b/f\n+\xff\xfe\n")

    text = code_patch_texts(storage, APP, KEY)["working_tree"]

    assert text.startswith("diff --git a/f b/f\n+") and "�" in text


def test_a_records_own_patches_load_the_same_way(tmp_path):
    storage = _storage(tmp_path)
    storage.save(APP, "v1", {"verstr": "v1"}, {"working_tree": WT, "untracked_files": b"TAR"})
    read = _spy_reads(storage)

    assert record_patch_texts(storage, APP, "v1") == {"working_tree": WT}
    assert not [name for name in read if name.endswith(".tar.gz")]


def test_patch_items_put_each_deps_texts_under_its_path():
    patches = {"working_tree": "a", "local_commits": "b",
               "deps": {"../z": {"local_commits": "d"}, "../a": {"working_tree": "c"}}}

    assert patch_items(patches) == ["a", "b", ("../a", "c"), ("../z", "d")]
    assert patch_items({}) == []


def test_a_code_object_without_dep_patches_reads_no_dep_files(tmp_path):
    storage = _storage(tmp_path)
    store_code(storage, APP, KEY, {"working_tree": WT}, dict(SUMMARY, has_dep_patches=False))
    read = _spy_reads(code_storage(storage))

    assert code_patch_texts(storage, APP, KEY, dep_paths=["../dep"]) == {"working_tree": WT}
    assert not [name for name in read if name.startswith("deps/")]
