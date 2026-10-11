"""A rerun's ``features`` author is the rerunner alone: without a git email or
``VMN_EXP_AUTHOR`` it keeps the rerunner's host identity (source ``host``),
never the original's local-commit ``From:``; copying the original's entry
reads none of its patches."""
from types import SimpleNamespace

import pytest
import vmn_exp.gitmode.features as gitmode_features
from version_stamp.core import logging as vmn_logging
from vmn_exp.core import identity
from vmn_exp.core import writer as experiment_writer
from vmn_exp.core.features import FEATURES_VERSION

LOCAL_COMMITS = (
    "From 1111111111111111111111111111111111111111 Mon Sep 17 00:00:00 2001\n"
    "From: Original Author <orig@x.io>\n"
    "Date: Mon, 1 Jan 2024 00:00:00 +0000\n"
    "Subject: [PATCH] tune lr\n"
    "\n"
    "---\n"
    "diff --git a/train.py b/train.py\n"
    "--- a/train.py\n"
    "+++ b/train.py\n"
    "@@ -1 +1 @@\n"
    "-lr = 1\n"
    "+lr = 2\n"
)


@pytest.fixture(autouse=True)
def _rerunner(monkeypatch, tmp_path):
    vmn_logging.ensure_logger()
    monkeypatch.setenv("VMN_WRITER_ID", "rerun-host")
    monkeypatch.setenv("USER", "bob")
    monkeypatch.delenv(identity.AUTHOR_ENV, raising=False)
    monkeypatch.setattr(identity, "_git_user_email", lambda cwd=None, **kw: "")
    experiment_writer._WRITER_ID = None
    yield
    experiment_writer._WRITER_ID = None


def _vcs(tmp_path):
    return SimpleNamespace(backend=SimpleNamespace(repo_path=str(tmp_path)))


def _original_features():
    return {"type": "features", "features_version": FEATURES_VERSION, "source": "capture",
            "author": {"git_user_email": "orig@x.io", "source": "git"},
            "changed": {"files": ["train.py"]}, "commits": ["tune lr"]}


def test_a_rerun_without_an_email_is_the_rerunners_host_not_the_original_committer(
    tmp_path,
):
    entry = gitmode_features.rerun_features(
        _vcs(tmp_path), [], {}, {"local_commits": LOCAL_COMMITS})
    assert entry["changed"]["files"] == ["train.py"]
    assert entry["author"] == {"writer": "rerun-host", "os_user": "bob", "source": "host"}


def test_vmn_exp_author_still_names_the_rerunner(tmp_path, monkeypatch):
    monkeypatch.setenv(identity.AUTHOR_ENV, "bob@x.io")
    entry = gitmode_features.rerun_features(
        _vcs(tmp_path), [], {}, {"local_commits": LOCAL_COMMITS})
    assert entry["author"]["git_user_email"] == "bob@x.io"
    assert entry["author"]["source"] == "env"


def test_copying_the_originals_features_parses_none_of_its_patches(
    tmp_path, monkeypatch,
):
    def _no_parse(texts):
        raise AssertionError("the original's patches were parsed")

    monkeypatch.setattr(gitmode_features, "features_from_patches", _no_parse)
    entry = gitmode_features.rerun_features(
        _vcs(tmp_path), [_original_features()], {}, {"local_commits": LOCAL_COMMITS})
    assert entry["source"] == "rerun"
    assert entry["changed"] == {"files": ["train.py"]}
    assert entry["commits"] == ["tune lr"]
    assert entry["author"] == {"writer": "rerun-host", "os_user": "bob", "source": "host"}
