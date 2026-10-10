"""Features log entries: caps, the truncated flag, empty-value dropping, commit authors."""
from vmn_exp.core.features import (
    FEATURES_VERSION,
    author_from_commits,
    build_features_entry,
    features_from_patches,
)


def _diff(path, context=""):
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@ {context}\n-a\n+b\n"


def _mail(subject):
    return (f"From {'0' * 40} Mon Sep 17 00:00:00 2001\nFrom: A <a@x.io>\n"
            f"Subject: [PATCH] {subject}\n\nbody\n---\n\n")


def test_features_version_is_one():
    assert FEATURES_VERSION == 1


def test_parsing_caps_files_at_200_and_flags_truncated():
    result = features_from_patches([_diff(f"f{i}.py") for i in range(201)])
    assert len(result["changed"]["files"]) == 200
    assert result["changed"]["files"][-1] == "f199.py"
    assert result["truncated"] is True


def test_parsing_caps_symbols_at_500():
    texts = [_diff(f"f{i % 100}.py", f"def s{i}():") for i in range(501)]
    result = features_from_patches(texts)
    assert len(result["changed"]["symbols"]) == 500
    assert result["truncated"] is True


def test_parsing_caps_commits_and_their_authors_at_50():
    result = features_from_patches(["".join(_mail(f"c{i}") for i in range(51))])
    assert result["commits"] == [f"c{i}" for i in range(50)]
    assert len(result["commit_authors"]) == 50
    assert result["truncated"] is True


def test_exactly_the_cap_after_deduplication_is_not_truncated():
    texts = [_diff(f"f{i}.py") for i in range(200)] * 2
    assert "truncated" not in features_from_patches(texts)


def test_an_entry_carries_type_version_source_and_the_given_facts():
    entry = build_features_entry(
        "capture",
        author={"writer": "gpu-07", "git_user_email": "a@x.io", "os_user": "alice", "source": "git"},
        changed={"files": ["a.py"], "symbols": ["a.py::f"], "untracked": ["notes.md"]},
        commits=["try focal loss"],
        entrypoint="train.py",
    )
    assert entry == {
        "type": "features",
        "features_version": FEATURES_VERSION,
        "source": "capture",
        "author": {"writer": "gpu-07", "git_user_email": "a@x.io", "os_user": "alice",
                   "source": "git"},
        "changed": {"files": ["a.py"], "symbols": ["a.py::f"], "untracked": ["notes.md"]},
        "commits": ["try focal loss"],
        "entrypoint": "train.py",
    }


def test_empty_values_and_empty_author_keys_are_dropped():
    entry = build_features_entry(
        "backfill",
        author={"writer": "w1", "git_user_email": "", "os_user": None, "source": "commit"},
        changed={"files": [], "symbols": [], "untracked": []},
        commits=[],
        branch="",
        entrypoint=None,
        truncated=False,
    )
    assert entry == {"type": "features", "features_version": FEATURES_VERSION,
                     "source": "backfill", "author": {"writer": "w1", "source": "commit"}}


def test_an_author_with_only_empty_values_is_omitted():
    entry = build_features_entry("capture", author={"writer": "", "git_user_email": ""})
    assert "author" not in entry


def test_the_entry_applies_the_caps_and_flags_truncated():
    entry = build_features_entry(
        "capture",
        changed={"files": [f"f{i}" for i in range(201)],
                 "symbols": [f"s{i}" for i in range(501)],
                 "untracked": [f"u{i}" for i in range(201)]},
        commits=[f"c{i}" for i in range(51)],
    )
    assert [len(entry["changed"][k]) for k in ("files", "symbols", "untracked")] == [200, 500, 200]
    assert len(entry["commits"]) == 50
    assert entry["truncated"] is True


def test_parsed_features_splat_into_an_entry_without_commit_authors():
    parsed = features_from_patches([_mail("one") + _diff("a.py", "def f():")])
    entry = build_features_entry("capture", **parsed)
    assert entry["changed"] == {"files": ["a.py"], "symbols": ["a.py::f"]}
    assert entry["commits"] == ["one"]
    assert "commit_authors" not in entry and "truncated" not in entry


def test_a_truncated_parse_stays_truncated_in_the_entry():
    parsed = features_from_patches([_diff(f"f{i}.py") for i in range(201)])
    assert build_features_entry("capture", **parsed)["truncated"] is True


def test_the_author_of_the_first_local_commit_with_an_email_is_used():
    authors = [{"name": "Nobody", "email": ""}, {"name": "A", "email": "a@x.io"},
               {"name": "B", "email": "b@x.io"}]
    assert author_from_commits(authors) == {"git_user_email": "a@x.io", "source": "commit"}


def test_no_commit_author_gives_none():
    assert author_from_commits([]) is None
    assert author_from_commits(None) is None
    assert author_from_commits([{"name": "Nobody", "email": ""}]) is None
