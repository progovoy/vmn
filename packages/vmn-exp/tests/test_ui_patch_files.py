"""``files`` of the ``/patch`` payload: ``[{path, added, removed}]`` counted
from the hunks of ``show --patch``'s sectioned text."""
from vmn_exp.ui.readers.patch_files import patch_files

WORKING = (
    "=== working_tree ===\n"
    "diff --git a/train.py b/train.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/train.py\n"
    "+++ b/train.py\n"
    "@@ -1,3 +1,3 @@\n"
    " import os\n"
    "-lr = 0.1\n"
    "+lr = 0.01\n"
    " run()\n"
)

COMMITS = (
    "=== local_commits ===\n"
    "From 0123456789012345678901234567890123456789 Mon Sep 17 00:00:00 2001\n"
    "From: A <a@x>\n"
    "Subject: [PATCH] add loss\n"
    "\n"
    "- a message line that looks removed\n"
    "---\n"
    " loss.py | 2 ++\n"
    "\n"
    "diff --git a/loss.py b/loss.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/loss.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+def loss():\n"
    "+    pass\n"
    "-- \n"
    "2.40.0\n"
    "\n"
)

DEP = (
    "=== deps/lib/working_tree ===\n"
    "diff --git a/util.py b/util.py\n"
    "--- a/util.py\n"
    "+++ b/util.py\n"
    "@@ -1 +1 @@\n"
    "-x = 1\n"
    "+x = 2\n"
)


def test_counts_each_files_added_and_removed_lines():
    assert patch_files(WORKING) == [{"path": "train.py", "added": 1, "removed": 1}]


def test_format_patch_messages_and_signatures_are_not_changes():
    assert patch_files(COMMITS) == [{"path": "loss.py", "added": 2, "removed": 0}]


def test_sections_add_up_per_path_in_order_of_appearance():
    again = WORKING.replace("=== working_tree ===", "=== local_commits ===")
    assert patch_files(WORKING + COMMITS + again) == [
        {"path": "train.py", "added": 2, "removed": 2},
        {"path": "loss.py", "added": 2, "removed": 0},
    ]


def test_dep_sections_name_their_files_under_the_dep():
    assert patch_files(DEP) == [{"path": "deps/lib/util.py", "added": 1, "removed": 1}]


def test_a_truncated_text_counts_what_it_holds():
    cut = WORKING[: WORKING.index("+lr")]
    assert patch_files(cut) == [{"path": "train.py", "added": 0, "removed": 1}]


def test_no_text_has_no_files():
    assert patch_files(None) == []
    assert patch_files("") == []
