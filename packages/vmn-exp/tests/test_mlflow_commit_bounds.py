"""``import-mlflow --repo``'s branch diff in checkouts as CI leaves them and
on huge branches: the default branch falls back to ``origin/main`` and
``origin/master`` when no local one exists (a dangling origin/HEAD counts as
none), the diff runs no textconv or external diff driver, and git's output
is read up to ``MAX_DIFF_BYTES`` only, marking the changes ``truncated``."""
from __future__ import annotations

import os

import pytest
from test_mlflow_commit_changes import TRAIN, _commit, _git, _init
from vmn_exp.importers import commit_changes
from vmn_exp.importers.commit_changes import CommitChanges, default_branch


def _ci_checkout(tmp_path, remote_branch):
    """A detached checkout of a feature tip whose only default-branch ref is
    ``refs/remotes/origin/<remote_branch>``. Returns (path, tip)."""
    path = _init(tmp_path / "ci", branch="trunk")
    _commit(path, {"train.py": TRAIN}, "base")
    _git(path, "update-ref", f"refs/remotes/origin/{remote_branch}", "HEAD")
    tip = _commit(path, {"loss.py": "def focal():\n    return 0\n"}, "focal")
    _git(path, "checkout", "-q", "--detach")
    _git(path, "branch", "-D", "trunk")
    return path, tip


@pytest.mark.parametrize("remote_branch", ["main", "master"])
def test_a_ci_checkout_falls_back_to_the_remote_default_branch(tmp_path, remote_branch):
    path, tip = _ci_checkout(tmp_path, remote_branch)

    assert default_branch(str(path)) == f"refs/remotes/origin/{remote_branch}"
    assert CommitChanges(str(path))(tip)["changed"]["files"] == ["loss.py"]


def test_a_local_default_branch_wins_over_the_remote_ones(tmp_path):
    path = _init(tmp_path / "repo", branch="master")
    _commit(path, {"a.py": "x = 1\n"}, "base")
    _git(path, "update-ref", "refs/remotes/origin/main", "HEAD")

    assert default_branch(str(path)) == "master"


def test_a_dangling_origin_head_is_no_default_branch(tmp_path):
    path = _init(tmp_path / "repo", branch="main")
    _commit(path, {"a.py": "x = 1\n"}, "base")
    _git(path, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")

    assert default_branch(str(path)) == "main"


def _marker_script(tmp_path, name):
    """A diff driver that leaves *name* behind when git runs it."""
    marker = tmp_path / name
    script = tmp_path / f"{name}.sh"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\ncat \"$1\" 2>/dev/null\n")
    os.chmod(script, 0o755)
    return marker, script


def test_the_branch_diff_runs_no_textconv_or_external_diff(tmp_path):
    path = _init(tmp_path / "repo", branch="main")
    textconv, conv = _marker_script(tmp_path, "textconv-ran")
    external, ext = _marker_script(tmp_path, "external-ran")
    (path / ".gitattributes").write_text("*.txt diff=marker\n")
    _git(path, "config", "diff.marker.textconv", str(conv))
    _git(path, "config", "diff.external", str(ext))
    _commit(path, {"notes.txt": "a\n"}, "base")
    _git(path, "checkout", "-q", "-b", "feat")
    tip = _commit(path, {"notes.txt": "b\n"}, "edit")

    result = CommitChanges(str(path))(tip)

    assert result["changed"]["files"] == ["notes.txt"]
    assert not textconv.exists() and not external.exists()


def test_a_huge_branch_diff_is_read_up_to_the_cap_and_marked_truncated(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(commit_changes, "MAX_DIFF_BYTES", 4000)
    path = _init(tmp_path / "repo", branch="main")
    _commit(path, {"keep.py": "x = 1\n"}, "base")
    _git(path, "checkout", "-q", "-b", "feat")
    files = {f"f{i:02d}.py": "".join(f"v{j} = {j}\n" for j in range(20)) for i in range(40)}
    tip = _commit(path, files, "many files")

    result = CommitChanges(str(path))(tip)

    assert result["truncated"] is True
    assert 0 < len(result["changed"]["files"]) < len(files)
    assert set(result["changed"]["files"]) <= set(files)
