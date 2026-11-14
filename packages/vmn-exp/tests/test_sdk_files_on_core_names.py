"""``vmn_exp.storage.files`` takes the record format's names from core's
``version_stamp.store.names`` (plan 37 P5f); where the two read or write
differently the SDK keeps its own behavior, pinned here."""
import os

import pytest

from version_stamp.store import names as core_names
from vmn_exp.storage import files

SHARED = [
    "METADATA_FILE", "PATCH_FILES", "safe_verstr", "unsafe_verstr",
    "safe_dep_name", "checked_app_path", "apply_metadata_updates",
]


@pytest.mark.parametrize("name", SHARED)
def test_record_format_names_are_cores(name):
    assert getattr(files, name) is getattr(core_names, name)


def test_reading_patches_skips_a_patch_path_that_is_not_a_file(tmp_path):
    os.mkdir(tmp_path / "working_tree.patch")
    (tmp_path / "local_commits.patch").write_text("diff")
    assert files.read_patches_from_dir(str(tmp_path)) == {"local_commits": "diff"}


def test_rewriting_a_patch_takes_the_umask_mode_not_the_old_files(tmp_path):
    path = tmp_path / "working_tree.patch"
    path.write_text("old")
    os.chmod(path, 0o600)
    mask = os.umask(0o022)
    try:
        files.write_patches_to_dir(str(tmp_path), {"working_tree": "new"})
    finally:
        os.umask(mask)
    assert path.read_text() == "new"
    assert os.stat(path).st_mode & 0o777 == 0o644
