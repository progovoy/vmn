"""Plan 39 B4c: which patch kinds make a run's own code a baseline."""
from vmn_exp.ui.readers.patches import has_own_code

NONE = {"working_tree": False, "local_commits": False, "untracked_files": False}


def test_untracked_files_alone_count_as_own_code():
    assert has_own_code({**NONE, "untracked_files": True})


def test_a_tracked_patch_counts_as_own_code():
    assert has_own_code({**NONE, "working_tree": True})
    assert has_own_code({**NONE, "local_commits": True})


def test_no_patch_kinds_is_no_own_code():
    assert not has_own_code(NONE)
