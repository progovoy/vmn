"""Reading a run's text patches tells a code object that is gone from one the
store could not read: ``None`` only when the store does not list it (its
marker, or the patch file), ``CodeReadError`` when a file the store lists
reads as nothing, and a read that raises propagates."""
import pytest
from vmn_exp.core.code_patches import (
    CodeReadError,
    code_patch_texts,
    record_patch_texts,
)
from vmn_exp.core.code_store import code_storage, store_code
from vmn_exp.storage.areas import local_store_root
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "root_app/svc"
KEY = "0.0.1-dev.abc1234.0000001.ffff"
WT = "diff --git a/src/loss.py b/src/loss.py\n+x\n"
LC = "From 0123 Mon Sep 17 00:00:00 2001\nFrom: A <a@x.io>\nSubject: [PATCH] one\n"
SUMMARY = {"has_working_tree_patch": True, "has_local_commits_patch": True,
           "has_untracked_files": False, "has_dep_patches": False}


@pytest.fixture
def storage(tmp_path):
    storage = LocalSnapshotStorage(local_store_root(str(tmp_path)), area="runs")
    store_code(storage, APP, KEY, {"working_tree": WT, "local_commits": LC}, SUMMARY)
    return storage


def _failing_reads(store, failing, fail=lambda name: None):
    """*store*'s reads of the *failing* file names go wrong (None, or *fail*'s raise)."""
    real = store.load_file

    def load_file(app_name, verstr, filename):
        return fail(filename) if filename in failing else real(app_name, verstr, filename)

    store.load_file = load_file


def test_a_listed_marker_that_reads_as_nothing_is_a_read_error(storage):
    _failing_reads(code_storage(storage), {"metadata.yml"})
    with pytest.raises(CodeReadError, match=KEY):
        code_patch_texts(storage, APP, KEY)


def test_a_marker_read_that_raises_propagates(storage):
    def boom(name):
        raise OSError("bucket on fire")

    _failing_reads(code_storage(storage), {"metadata.yml"}, boom)
    with pytest.raises(OSError, match="bucket on fire"):
        code_patch_texts(storage, APP, KEY)


def test_a_listed_patch_that_reads_as_nothing_is_a_read_error(storage):
    _failing_reads(code_storage(storage), {"local_commits.patch"})
    with pytest.raises(CodeReadError, match=r"local_commits\.patch"):
        code_patch_texts(storage, APP, KEY)


def test_a_patch_read_that_raises_propagates(storage):
    def boom(name):
        raise OSError("timeout")

    _failing_reads(code_storage(storage), {"working_tree.patch"}, boom)
    with pytest.raises(OSError, match="timeout"):
        code_patch_texts(storage, APP, KEY)


def test_a_patch_the_store_does_not_list_is_simply_absent(tmp_path):
    storage = LocalSnapshotStorage(local_store_root(str(tmp_path)), area="runs")
    store_code(storage, APP, KEY, {"working_tree": WT}, SUMMARY)
    assert code_patch_texts(storage, APP, KEY) == {"working_tree": WT}


def test_a_records_own_listed_patch_that_reads_as_nothing_is_a_read_error(tmp_path):
    storage = LocalSnapshotStorage(local_store_root(str(tmp_path)), area="runs")
    storage.save(APP, "v1", {"verstr": "v1"}, {"working_tree": WT})
    _failing_reads(storage, {"working_tree.patch"})
    with pytest.raises(CodeReadError, match=r"working_tree\.patch"):
        record_patch_texts(storage, APP, "v1")


def test_on_s3_a_marker_get_that_fails_is_a_read_error_not_a_missing_object(monkeypatch):
    from s3_helpers import mocked_bucket, s3_storage

    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        store_code(storage, APP, KEY, {"working_tree": WT}, SUMMARY)
        area = code_storage(storage)
        real_get = area._get
        # S3 answers None for any failed GET, not only a missing key.
        monkeypatch.setattr(area, "_get", lambda key: None if key.endswith(
            "/metadata.yml") else real_get(key))

        with pytest.raises(CodeReadError, match=KEY):
            code_patch_texts(storage, APP, KEY)
        assert code_patch_texts(storage, APP, KEY + "0") is None
