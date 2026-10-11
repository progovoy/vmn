"""A snapshot capture keeps the untracked paths it hashed
(``SnapshotCapture.untracked_paths``), listing the repo's untracked files once:
callers needing those paths (vmn-exp's run features) reuse them instead of
walking the tree again."""
import os

import pytest
from helpers import _bootstrap
from version_stamp.api import VMN_BE_TYPE_GIT, VersionControlStamper
from version_stamp.core import logging as vmn_logging
from version_stamp.devversion import capture as devversion_capture
from version_stamp.devversion import untracked
from version_stamp.snapshot.capture import capture_identity


@pytest.fixture(autouse=True)
def _logger():
    vmn_logging.ensure_logger()


def _vcs(app_layout):
    return VersionControlStamper({"root": False, "name": app_layout.app_name,
                                  "root_path": app_layout.repo_path,
                                  "be_type": VMN_BE_TYPE_GIT})


def _write(app_layout, name, text="x\n"):
    path = os.path.join(app_layout.repo_path, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def test_the_capture_keeps_the_untracked_paths_it_hashed(app_layout):
    _bootstrap(app_layout)
    _write(app_layout, "notes/b.md")
    _write(app_layout, "a.md")

    captured, err = capture_identity(_vcs(app_layout))

    assert err is None and captured.identity.get("untracked_hash")
    assert captured.untracked_paths == ["a.md", "notes/b.md"]


def test_a_tree_without_untracked_files_has_none(app_layout):
    _bootstrap(app_layout)

    captured, err = capture_identity(_vcs(app_layout))

    assert err is None and captured.untracked_paths == []


def test_the_capture_lists_the_untracked_files_once(app_layout, monkeypatch):
    _bootstrap(app_layout)
    _write(app_layout, "a.md")
    vcs = _vcs(app_layout)
    listed = []
    real = untracked._untracked_stats

    def counting(repo_path):
        listed.append(repo_path)
        return real(repo_path)

    monkeypatch.setattr(untracked, "_untracked_stats", counting)
    monkeypatch.setattr(devversion_capture, "_untracked_stats", counting)

    captured, _ = capture_identity(vcs)

    assert listed.count(vcs.backend.repo_path) == 1
    assert captured.untracked_paths == ["a.md"]
