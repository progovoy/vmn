"""The ``show --patch`` payload: a run's own text patches, labelled and capped."""
import io
import tarfile

from vmn_exp.cli.views import PATCH_MAX_BYTES, no_patch_note, patch_payload

WORKING = "diff --git a/f b/f\n-old\n+new\n"
COMMITS = "From 0123 Mon Sep 17 00:00:00 2001\nSubject: [PATCH] try it\n"


def test_patch_payload_labels_working_tree_then_local_commits():
    payload = patch_payload({}, {"local_commits": COMMITS, "working_tree": WORKING})
    assert payload == {
        "text": f"=== working_tree ===\n{WORKING}=== local_commits ===\n{COMMITS}",
        "truncated": False,
    }


def test_dep_patches_follow_the_runs_own_labelled_by_dep():
    patches = {
        "working_tree": WORKING,
        "deps": {
            "libs_b": {"local_commits": COMMITS},
            "libs_a": {"working_tree": "diff --git a/x b/x\n"},
        },
    }
    text = patch_payload({}, patches)["text"]
    labels = [line for line in text.splitlines() if line.startswith("=== ")]
    assert labels == [
        "=== working_tree ===",
        "=== deps/libs_a/working_tree ===",
        "=== deps/libs_b/local_commits ===",
    ]


def test_the_untracked_tarball_is_never_part_of_the_text():
    patches = {
        "working_tree": WORKING,
        "untracked_files": b"\x1f\x8bTAR",
        "deps": {"d": {"untracked_files": b"\x1f\x8bDEP"}},
    }
    text = patch_payload({}, patches)["text"]
    assert "TAR" not in text and "DEP" not in text and "untracked" not in text


def test_a_patch_without_a_final_newline_does_not_run_into_the_next_label():
    text = patch_payload({}, {"working_tree": "+x", "local_commits": COMMITS})["text"]
    assert "+x\n=== local_commits ===\n" in text


def _tarball(*names):
    buf = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=buf) as tar:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = 2
            tar.addfile(info, io.BytesIO(b"x\n"))
    return buf.getvalue()


def test_no_text_patch_means_no_code():
    assert patch_payload({}, {}) == {"text": None, "reason": "no_code"}


def test_untracked_files_alone_are_their_own_reason_listing_their_names():
    meta = {"base_commit": "f" * 40, "code": "k", "has_untracked_files": True}
    tar_only = {"untracked_files": _tarball("new_script.py", "data/a.csv")}
    assert patch_payload(meta, tar_only) == {
        "text": None,
        "reason": "untracked_only",
        "untracked_files": ["data/a.csv", "new_script.py"],
    }


def test_a_deps_untracked_files_alone_are_labelled_by_dep():
    patches = {"deps": {"libs_b": {"untracked_files": _tarball("gen.py")}}}
    payload = patch_payload({"base_commit": "f" * 40}, patches)
    assert payload["reason"] == "untracked_only"
    assert payload["untracked_files"] == ["deps/libs_b/gen.py"]


def test_a_missing_code_object_is_its_own_reason():
    meta = {"code": "0.0.1-dev.abc.def.1234", "code_missing": True}
    assert patch_payload(meta, {}) == {"text": None, "reason": "code_missing"}


def test_text_is_capped_on_a_utf8_boundary():
    payload = patch_payload({}, {"working_tree": "+" + "é" * 50 + "\n"}, max_bytes=30)
    assert payload["truncated"] is True
    raw = payload["text"].encode("utf-8")
    assert len(raw) <= 30
    assert payload["text"].startswith("=== working_tree ===\n+é")
    assert "�" not in payload["text"]


def test_the_default_cap_is_200000_bytes():
    assert PATCH_MAX_BYTES == 200000
    payload = patch_payload({}, {"working_tree": "+" + "x" * 300000 + "\n"})
    assert payload["truncated"] is True
    assert len(payload["text"].encode("utf-8")) == 200000


def test_text_within_the_cap_is_whole():
    payload = patch_payload({}, {"working_tree": WORKING}, max_bytes=10 ** 6)
    assert payload == {"text": f"=== working_tree ===\n{WORKING}", "truncated": False}


def test_no_patch_note_names_the_run_and_why():
    imported = {"imported_from": {"tool": "mlflow", "run_id": "abc"}}
    note = no_patch_note("0.0.1-dev.r1", imported)
    assert "\n" not in note
    assert "0.0.1-dev.r1" in note and "imported from mlflow run abc" in note
    missing = {"code": "k", "code_missing": True, "base_commit": "f" * 40}
    assert "code snapshot k is missing" in no_patch_note("v", missing)


def test_no_patch_note_of_a_clean_tree_run_names_its_commit():
    note = no_patch_note("0.0.2", {"base_commit": "abcdef0123456789"})
    assert "\n" not in note
    assert "clean tree" in note and "abcdef0" in note


def test_no_patch_note_of_an_exported_snapshot_run_says_so():
    meta = {"base_commit": "abcdef0123", "from_snapshot": True}
    assert "exported snapshot" in no_patch_note("v", meta)


def test_no_patch_note_of_an_untracked_only_run_names_the_files_not_a_clean_tree():
    meta = {"base_commit": "abcdef0123", "code": "k", "has_untracked_files": True}
    note = no_patch_note("v", meta, untracked=["new_script.py"])
    assert "\n" not in note
    assert "clean tree" not in note
    assert "untracked" in note and "new_script.py" in note
    assert "vmn-exp export" in note


def test_no_patch_note_lists_at_most_three_untracked_names():
    names = [f"f{i}.py" for i in range(5)]
    note = no_patch_note("v", {"base_commit": "abcdef0123"}, untracked=names)
    assert "f0.py, f1.py, f2.py" in note and "f3.py" not in note
    assert "+2 more" in note
