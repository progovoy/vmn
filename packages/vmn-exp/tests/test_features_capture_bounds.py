"""Features capture runs under the repo lock, so it must stay quick: the
author's ``git config user.email`` gives up after 2 seconds, and the
untracked paths come from the snapshot capture's own listing when it has
one (the tree is walked again only for a capture without it)."""
import os
import time
from types import SimpleNamespace

import pytest
import vmn_exp.gitmode.features as gitmode_features
from version_stamp.core import logging as vmn_logging
from vmn_exp.core import identity
from vmn_exp.core import writer as experiment_writer

HANG_SEC = 8
WT = "diff --git a/train.py b/train.py\n--- a/train.py\n+++ b/train.py\n@@ -1 +1 @@\n-a\n+b\n"


@pytest.fixture(autouse=True)
def _host(monkeypatch):
    vmn_logging.ensure_logger()
    monkeypatch.setenv("VMN_WRITER_ID", "gpu-07")
    monkeypatch.delenv(identity.AUTHOR_ENV, raising=False)
    experiment_writer._WRITER_ID = None
    yield
    experiment_writer._WRITER_ID = None


@pytest.fixture
def hanging_git(tmp_path, monkeypatch):
    """Every ``git`` on PATH hangs for HANG_SEC seconds."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text(f"#!/bin/sh\nexec sleep {HANG_SEC}\n")
    os.chmod(git, 0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def _vcs(tmp_path):
    return SimpleNamespace(backend=SimpleNamespace(repo_path=str(tmp_path)))


def _timed(call):
    start = time.monotonic()
    result = call()
    return result, time.monotonic() - start


def test_a_hanging_git_config_gives_no_email_within_two_seconds(tmp_path, hanging_git):
    email, took = _timed(lambda: identity._git_user_email(cwd=str(tmp_path)))
    assert email == ""
    assert took < 4


def test_capture_takes_the_untracked_paths_the_snapshot_listed(tmp_path, hanging_git):
    captured = SimpleNamespace(identity={"working_tree": WT, "untracked_hash": b"h"},
                               untracked_paths=["notes/b.md", "a.md"])

    entry, took = _timed(lambda: gitmode_features.capture_features(_vcs(tmp_path), captured))

    assert took < 4
    assert entry["changed"] == {"files": ["train.py"], "untracked": ["a.md", "notes/b.md"]}
    assert entry["author"] == {"writer": "gpu-07", "os_user": entry["author"]["os_user"],
                               "source": "host"}


def test_capture_never_walks_the_tree_when_the_snapshot_listed_it(tmp_path, monkeypatch):
    def walk(repo_path):
        raise AssertionError("walked the tree a second time")

    monkeypatch.setattr(gitmode_features, "_untracked_candidates", walk)
    monkeypatch.setattr(identity, "_git_user_email", lambda cwd=None: "")
    captured = SimpleNamespace(identity={"untracked_hash": b"h"}, untracked_paths=["a.md"])

    entry = gitmode_features.capture_features(_vcs(tmp_path), captured)

    assert entry["changed"] == {"untracked": ["a.md"]}


def test_a_capture_without_its_listing_walks_the_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(gitmode_features, "_untracked_candidates",
                        lambda repo_path: [("z.py", "/abs/z.py", 1), ("a.py", "/abs/a.py", 1)])
    monkeypatch.setattr(identity, "_git_user_email", lambda cwd=None: "")
    captured = SimpleNamespace(identity={"untracked_hash": b"h"})

    entry = gitmode_features.capture_features(_vcs(tmp_path), captured)

    assert entry["changed"] == {"untracked": ["a.py", "z.py"]}
