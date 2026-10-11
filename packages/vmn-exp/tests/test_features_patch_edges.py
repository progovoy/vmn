"""features_from_patches on the edges of git's output: line separators other
than newline inside content lines, a commit message quoting a diff header, a
format-patch cover letter, and blank list items in the features entry."""
import pytest
from test_features_git_patches import _write, repo  # noqa: F401
from vmn_exp.core.features import build_features_entry, features_from_patches

SHA = "3d71d1bf894eea3f06c2c57b7bfbf77610a7ea8c"


def _mail(subject, message, diff, from_line="From: Alice <a@x.io>", stat=True):
    lines = [f"From {SHA} Mon Sep 17 00:00:00 2001", from_line,
             "Date: Sun, 11 Oct 2026 00:29:47 +0300", f"Subject: {subject}", "", *message]
    lines += ["---", " x.py | 2 +-", ""] if stat else [""]
    return "\n".join(lines + [diff, "-- ", "2.50.1", "", ""])


DIFF = ("diff --git a/x.py b/x.py\nindex 1..2 100644\n--- a/x.py\n+++ b/x.py\n"
        "@@ -1,2 +1,2 @@ def real():\n-a\n+b\n")


@pytest.mark.parametrize("separator", ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85",
                                       " ", " "])
def test_only_a_newline_ends_a_line(separator):
    text = (
        "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@ def real():\n"
        f"-a{separator}@@ -9 +9 @@ def bogus():\n"
        f"+b{separator}diff --git a/evil b/evil\n"
    )
    result = features_from_patches([text])
    assert result["changed"] == {"files": ["x.py"], "symbols": ["x.py::real"]}


def test_a_diff_header_quoted_in_a_commit_message_is_no_file():
    message = ["quote of a diff:", "diff --git a/fake b/fake", "and more", "",
               "diff --git a/fake2 b/fake2", "not an extended header line"]
    result = features_from_patches([_mail("[PATCH] real", message, DIFF)])
    assert result["changed"] == {"files": ["x.py"], "symbols": ["x.py::real"]}
    assert result["commits"] == ["real"]


def test_a_mbox_without_a_diffstat_still_names_its_files():
    result = features_from_patches([_mail("[PATCH] real", ["body"], DIFF, stat=False)])
    assert result["changed"] == {"files": ["x.py"], "symbols": ["x.py::real"]}


@pytest.mark.parametrize("subject", ["[PATCH 0/2] *** SUBJECT HERE ***",
                                     "[PATCH v2 00/12] the series", "[RFC PATCH 0/1] x"])
def test_a_cover_letter_is_no_commit(subject):
    cover = _mail(subject, ["*** BLURB HERE ***", "", "Bob (2):", "  real"], "",
                  from_line="From: Bob <bob@x.io>")
    patch = _mail("[PATCH 1/2] real", ["body"], DIFF)
    tenth = _mail("[PATCH 10/12] tenth", ["body"], "")
    result = features_from_patches([cover + patch + tenth])
    assert result["commits"] == ["real", "tenth"]
    assert result["commit_authors"] == [{"name": "Alice", "email": "a@x.io"}] * 2
    assert result["changed"]["files"] == ["x.py"]


def test_real_format_patch_output_with_a_cover_letter_and_a_quoted_header(repo):  # noqa: F811
    path, git = repo
    _write(path, {"model.py": "def train(x):\n    return 2\n"})
    git("add", "-A")
    git("commit", "-qm", "change train\n\nit mentions\ndiff --git a/fake b/fake\nin its body",
        author=("Ann", "ann@x.io"))
    for flags in (["--cover-letter"], ["--no-stat"], []):
        mbox = git("format-patch", "--stdout", *flags, "base..HEAD")
        result = features_from_patches([mbox])
        assert result["changed"]["files"] == ["model.py"], flags
        assert result["commits"] == ["change train"], flags
        assert result["commit_authors"] == [{"name": "Ann", "email": "ann@x.io"}], flags


PASTED_DIFF = ("The upstream fix we port looks like this:\n\n"
               "diff --git a/vendor/fake.py b/vendor/fake.py\nindex 1111111..2222222 100644\n"
               "--- a/vendor/fake.py\n+++ b/vendor/fake.py\n@@ -1,2 +1,2 @@ def vendored():\n"
               " y = 0\n-x = 1\n+x = 2\n")


@pytest.mark.parametrize("trailer", ["\nSigned-off-by: Ann <ann@x.io>", ""],
                         ids=["text-after-the-diff", "message-ends-with-the-diff"])
def test_a_diff_pasted_into_a_commit_message_names_no_file(repo, trailer):  # noqa: F811
    path, git = repo
    with open(path / "model.py", "a") as f:
        f.write("\n\ndef focal_loss(x):\n    return x\n")
    git("commit", "-qam", f"add focal loss\n\n{PASTED_DIFF}{trailer}")
    mbox = git("format-patch", "--stdout", "base..HEAD")
    assert "\ndiff --git a/vendor/fake.py" in mbox
    result = features_from_patches([mbox])
    assert result["changed"] == {"files": ["model.py"],
                                 "symbols": ["model.py::forward", "model.py::focal_loss"]}
    no_stat = features_from_patches([git("format-patch", "--stdout", "--no-stat", "base..HEAD")])
    assert "model.py::focal_loss" in no_stat["changed"]["symbols"]


def test_a_pasted_diff_ends_at_the_separator_even_without_a_hunk():
    message = ["see", "", "diff --git a/fake b/fake", "index 1..2 100644", "", "more"]
    result = features_from_patches([_mail("[PATCH] real", message, DIFF)])
    assert result["changed"] == {"files": ["x.py"], "symbols": ["x.py::real"]}


def test_a_removed_double_dash_line_is_no_separator_after_a_pasted_diff(repo):  # noqa: F811
    path, git = repo
    _write(path, {"q.sql": "-- schema\n--\nselect 1;\n"})
    git("add", "-A")
    git("commit", "-qm", "sql")
    git("tag", "-f", "base")
    _write(path, {"q.sql": "-- schema\nselect 1;\n"})
    git("commit", "-qam", f"drop the empty comment\n\n{PASTED_DIFF}")
    mbox = git("format-patch", "--stdout", "--no-stat", "base..HEAD")
    assert "\n---\n" in mbox.split("diff --git a/q.sql")[1]
    assert "q.sql" in features_from_patches([mbox])["changed"]["files"]


def test_blank_list_items_are_dropped_from_the_features_entry():
    entry = build_features_entry(
        "capture",
        changed={"files": ["a", "a", "", " ", None], "symbols": ["", "a::f"]},
        commits=["", "x", "  ", None],
    )
    assert entry["changed"] == {"files": ["a"], "symbols": ["a::f"]}
    assert entry["commits"] == ["x"]
    assert "changed" not in build_features_entry("capture", changed={"files": ["", " "]})
