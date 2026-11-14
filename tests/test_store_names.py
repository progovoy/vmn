"""``version_stamp.store.names``: the record format's names and patch dirs."""
import pytest

from version_stamp.snapshot import identity, local_store, record
from version_stamp.store import names


@pytest.mark.parametrize("verstr", ["1.0+x", "0.0.1-dev.abcdef1.1234567", "1+a+b"])
def test_safe_verstr_round_trips(verstr):
    safe = names.safe_verstr(verstr)
    assert "+" not in safe
    assert names.unsafe_verstr(safe) == verstr


def test_safe_verstr_spells_plus_out():
    assert names.safe_verstr("1.0+x") == "1.0_plus_x"


@pytest.mark.parametrize("bad", ["..", "a/b", "", "."])
def test_safe_verstr_rejects_walking_names(bad):
    with pytest.raises(ValueError, match="Invalid record name"):
        names.safe_verstr(bad)


def test_safe_dep_name_flattens_the_path():
    assert names.safe_dep_name("../dep/sub") == ".._dep_sub"


@pytest.mark.parametrize("app", ["app", "root/svc"])
def test_checked_app_path_keeps_a_relative_app_path(app):
    assert names.checked_app_path(app) == app


@pytest.mark.parametrize("bad", ["../x", "/abs", "a/../b", ""])
def test_checked_app_path_rejects_path_walking(bad):
    with pytest.raises(ValueError, match="Invalid app name"):
        names.checked_app_path(bad)


def test_apply_metadata_updates_sets_and_drops_fields():
    metadata = {"note": "old", "keep": 1}
    out = names.apply_metadata_updates(metadata, {"note": None, "new": "v"})
    assert out is metadata
    assert metadata == {"keep": 1, "new": "v"}


def test_patches_round_trip_through_a_dir(tmp_path):
    patches = {
        "working_tree": "diff --git a b\n",
        "local_commits": "From abc\n",
        "untracked_files": b"\x1f\x8b binary",
    }
    names.write_patches_to_dir(str(tmp_path), patches)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "local_commits.patch", "untracked_files.tar.gz", "working_tree.patch",
    ]
    assert names.read_patches_from_dir(str(tmp_path)) == patches


def test_writing_patches_drops_the_files_a_record_lacks(tmp_path):
    names.write_patches_to_dir(str(tmp_path), {"working_tree": "a\n", "local_commits": "b\n"})
    names.write_patches_to_dir(str(tmp_path), {"working_tree": "c\n"})
    assert names.read_patches_from_dir(str(tmp_path)) == {"working_tree": "c\n"}


def test_reading_a_missing_dir_gives_no_patches(tmp_path):
    assert names.read_patches_from_dir(str(tmp_path / "absent")) == {}


def test_format_constants():
    assert names.METADATA_FILE == "metadata.yml"
    assert [f for _, f, _ in names.PATCH_FILES] == [
        "working_tree.patch", "local_commits.patch", "untracked_files.tar.gz",
    ]


@pytest.mark.parametrize("module, name", [
    (identity, "safe_verstr"), (identity, "unsafe_verstr"), (identity, "safe_dep_name"),
    (record, "METADATA_FILE"), (record, "PATCH_FILES"),
    (local_store, "safe_verstr"), (local_store, "METADATA_FILE"),
])
def test_snapshot_modules_re_export_the_store_names(module, name):
    assert getattr(module, name) is getattr(names, name)
