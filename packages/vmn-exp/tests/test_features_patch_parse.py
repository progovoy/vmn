"""features_from_patches over hand-written unified diffs and format-patch mboxes."""
from vmn_exp.core.features import features_from_patches

SHA = "3d71d1bf894eea3f06c2c57b7bfbf77610a7ea8c"


def _files(*texts):
    return features_from_patches(texts)["changed"]["files"]


def _symbols(*texts):
    return features_from_patches(texts)["changed"]["symbols"]


def _mail(subject_lines, body_diff, from_line="From: Alice <a@x.io>"):
    return "\n".join(
        [f"From {SHA} Mon Sep 17 00:00:00 2001", from_line,
         "Date: Sun, 11 Oct 2026 00:29:47 +0300", *subject_lines, "",
         "body paragraph", "---", " x.py | 2 +-", "", body_diff, "-- ", "2.50.1", "", ""]
    )


MODIFY = """\
diff --git a/src/loss.py b/src/loss.py
index ac9d405..00f8f4f 100644
--- a/src/loss.py
+++ b/src/loss.py
@@ -7,7 +7,7 @@ def focal_loss(x, gamma=2):
     a = 1
-    b = 2
+    b = 3
@@ -40,3 +40,4 @@ class Trainer:
     pass
+    pass
@@ -90,2 +91,2 @@ def focal_loss(x, gamma=2):
-    c = 1
+    c = 2
"""


def test_a_plain_diff_yields_the_file_and_one_symbol_per_hunk_context():
    result = features_from_patches([MODIFY])
    assert result["changed"] == {
        "files": ["src/loss.py"],
        "symbols": ["src/loss.py::focal_loss", "src/loss.py::Trainer"],
    }
    assert result["commits"] == [] and result["commit_authors"] == []
    assert "truncated" not in result


def test_hunks_without_context_add_no_symbol():
    text = "diff --git a/n.txt b/n.txt\n--- a/n.txt\n+++ b/n.txt\n@@ -1,3 +1,4 @@\n a\n+b\n"
    assert _symbols(text) == []
    assert _files(text) == ["n.txt"]


def test_new_deleted_and_mode_only_files_are_listed():
    text = (
        "diff --git a/new.py b/new.py\nnew file mode 100644\nindex 0000000..f150f5f\n"
        "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+z = 1\n"
        "diff --git a/gone.txt b/gone.txt\ndeleted file mode 100644\n"
        "--- a/gone.txt\n+++ /dev/null\n@@ -1 +0,0 @@ def gone():\n-bye\n"
        "diff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n"
    )
    assert _files(text) == ["new.py", "gone.txt", "run.sh"]
    assert _symbols(text) == ["gone.txt::gone"]


def test_a_rename_lists_both_paths_and_scopes_symbols_to_the_new_path():
    text = (
        "diff --git a/old name.py b/new name.py\nsimilarity index 90%\n"
        "rename from old name.py\nrename to new name.py\n"
        "--- a/old name.py\n+++ b/new name.py\n@@ -3,3 +3,3 @@ def moved():\n-a\n+b\n"
    )
    assert _files(text) == ["new name.py", "old name.py"]
    assert _symbols(text) == ["new name.py::moved"]


def test_a_copy_lists_only_the_copy():
    text = "diff --git a/a.py b/b.py\nsimilarity index 100%\ncopy from a.py\ncopy to b.py\n"
    assert _files(text) == ["b.py"]


def test_binary_files_are_listed_and_their_payload_is_not_parsed():
    text = (
        "diff --git a/img.bin b/img.bin\nnew file mode 100644\n"
        "index 0000000..c866266\nGIT binary patch\nliteral 256\n"
        "zcmV+b0ssC00RjUA1qKHQ2?`4g4Gs?w5fT#=6&4p585$cL9UdPbAtECrB_<~*DJm;0\n\n"
        "literal 0\nHcmV?d00001\n\n"
        "diff --git a/logo.png b/logo.png\nindex 1..2 100644\n"
        "Binary files a/logo.png and b/logo.png differ\n"
    )
    assert _files(text) == ["img.bin", "logo.png"]
    assert _symbols(text) == []


def test_paths_with_spaces_and_c_quoted_paths_are_decoded():
    text = (
        "diff --git a/my dir/a b.py b/my dir/a b.py\n--- a/my dir/a b.py\n"
        "+++ b/my dir/a b.py\n@@ -1 +1 @@ def f():\n-a\n+b\n"
        'diff --git "a/na\\303\\257ve \\"q\\".py" "b/na\\303\\257ve \\"q\\".py"\n'
        "index 1..2 100644\n"
    )
    assert _files(text) == ["my dir/a b.py", 'naïve "q".py']
    assert _symbols(text) == ["my dir/a b.py::f"]


def test_mnemonic_and_no_prefix_diffs_give_the_same_paths():
    mnemonic = "diff --git c/src/x.py w/src/x.py\n--- c/src/x.py\n+++ w/src/x.py\n"
    bare = "diff --git src/x.py src/x.py\n--- src/x.py\n+++ src/x.py\n"
    assert _files(mnemonic) == _files(bare) == ["src/x.py"]


def test_format_patch_subjects_drop_the_patch_prefix_and_unfold():
    first = _mail(["Subject: [PATCH 1/2] this is a very long subject that git folded by",
                   " format-patch because it is long"], MODIFY)
    second = _mail(["Subject: [PATCH 2/2] [WIP] keep my own brackets"], "")
    single = _mail(["Subject: [PATCH] one commit"], "")
    result = features_from_patches([first + second, single])
    assert result["commits"] == [
        "this is a very long subject that git folded by format-patch because it is long",
        "[WIP] keep my own brackets",
        "one commit",
    ]


def test_rfc2047_encoded_subjects_and_names_are_decoded():
    text = _mail(
        ["Subject: [PATCH] =?UTF-8?q?Caf=C3=A9:=20ajouter=20une=20tr=C3=A8s=20longue?=",
         " =?UTF-8?q?=20description?="],
        "",
        from_line="From: =?UTF-8?q?J=C3=B6rg=20M=C3=BCller?= <j@x.io>",
    )
    result = features_from_patches([text])
    assert result["commits"] == ["Café: ajouter une très longue description"]
    assert result["commit_authors"] == [{"name": "Jörg Müller", "email": "j@x.io"}]


def test_quoted_names_and_every_commit_author_are_kept_in_order():
    text = (_mail(["Subject: [PATCH 1/2] a"], "")
            + _mail(["Subject: [PATCH 2/2] b"], "", from_line='From: "Doe, John" <jd@x.io>'))
    assert features_from_patches([text])["commit_authors"] == [
        {"name": "Alice", "email": "a@x.io"},
        {"name": "Doe, John", "email": "jd@x.io"},
    ]


def test_the_mbox_from_line_is_not_an_author_and_diff_lines_are_not_headers():
    tricky = (
        "diff --git a/m.txt b/m.txt\n--- a/m.txt\n+++ b/m.txt\n@@ -1,2 +1,3 @@\n"
        "+From: Mallory <m@evil.io>\n+Subject: not a commit\n-diff --git a/z b/z\n"
        " @@ -1 +1 @@ def not_a_hunk():\n"
    )
    result = features_from_patches([_mail(["Subject: [PATCH] real"], tricky)])
    assert result["commit_authors"] == [{"name": "Alice", "email": "a@x.io"}]
    assert result["commits"] == ["real"]
    assert result["changed"] == {"files": ["m.txt"], "symbols": []}


def test_a_commit_body_line_starting_with_from_is_not_a_new_message():
    text = _mail(["Subject: [PATCH] real"], MODIFY).replace(
        "body paragraph", "From now on use focal loss\nFrom: someone <s@x.io>")
    result = features_from_patches([text])
    assert result["commit_authors"] == [{"name": "Alice", "email": "a@x.io"}]
    assert result["commits"] == ["real"]


def test_files_and_symbols_are_deduplicated_across_texts():
    result = features_from_patches([MODIFY, MODIFY.replace("Trainer", "Other")])
    assert result["changed"]["files"] == ["src/loss.py"]
    assert result["changed"]["symbols"] == [
        "src/loss.py::focal_loss", "src/loss.py::Trainer", "src/loss.py::Other"]


def test_empty_and_none_texts_are_skipped():
    assert features_from_patches([None, "", "   \n"]) == {
        "changed": {"files": [], "symbols": []}, "commits": [], "commit_authors": []}


def test_a_prefixed_text_scopes_its_paths_under_the_prefix():
    result = features_from_patches([("../dep/", MODIFY), MODIFY])
    assert result["changed"]["files"] == ["../dep/src/loss.py", "src/loss.py"]
    assert result["changed"]["symbols"][:2] == [
        "../dep/src/loss.py::focal_loss", "../dep/src/loss.py::Trainer"]


def test_crlf_line_endings_parse_like_lf():
    assert features_from_patches([MODIFY.replace("\n", "\r\n")]) == features_from_patches([MODIFY])
