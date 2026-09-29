"""``_apply_patches_to_workdir`` reports the steps that failed.

Callers that must not run wrong code (``vmn-exp rerun``) treat any failed step
as fatal; the others keep ignoring the return value.
"""
import subprocess

import pytest

from version_stamp.core.logging import ensure_logger
from version_stamp.devversion.apply import _apply_patches_to_workdir
from version_stamp.devversion.untracked import _collect_untracked_tarball

_IDENTITY_ENV = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "EMAIL",
)


def _git(cwd, *args, stdin=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, input=stdin, capture_output=True, text=True,
        check=True,
    ).stdout


def _commit(repo, name, content, message):
    (repo / name).write_text(content)
    _git(repo, "add", name)
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    ensure_logger()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in _IDENTITY_ENV:
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    _commit(path, "a.txt", "one\n", "base")
    return path


def _dirty_patches(repo):
    """Patches of a local commit + a working-tree edit + an untracked file,
    after which *repo* is reset back to its base."""
    base = _git(repo, "rev-parse", "HEAD").strip()
    _commit(repo, "b.txt", "local\n", "local commit")
    local_commits = _git(repo, "format-patch", "--stdout", f"{base}..HEAD")
    (repo / "a.txt").write_text("one\ntwo\n")
    working_tree = _git(repo, "diff", "HEAD")
    (repo / "new.txt").write_text("untracked\n")
    tarball, _ = _collect_untracked_tarball(str(repo))
    _git(repo, "reset", "-q", "--hard", base)
    _git(repo, "clean", "-qfd")
    return {
        "local_commits": local_commits,
        "working_tree": working_tree,
        "untracked_files": tarball,
    }


def test_apply_patches_success_returns_empty(repo):
    patches = _dirty_patches(repo)

    assert _apply_patches_to_workdir(str(repo), patches) == []
    assert (repo / "b.txt").read_text() == "local\n"
    assert (repo / "a.txt").read_text() == "one\ntwo\n"
    assert (repo / "new.txt").read_text() == "untracked\n"


def test_apply_patches_reports_failed_steps(repo):
    patches = {
        "local_commits": "not a mailbox\n",
        "working_tree": "garbage that is no diff\n",
        "untracked_files": b"not a tarball",
    }

    failed = _apply_patches_to_workdir(str(repo), patches)

    assert failed == ["local_commits", "working_tree", "untracked_files"]


def test_apply_patches_nothing_to_apply_returns_empty(repo):
    assert _apply_patches_to_workdir(str(repo), {}) == []


def test_git_am_gets_fallback_identity_when_none_configured(repo):
    patches = _dirty_patches(repo)
    _git(repo, "config", "user.useConfigOnly", "true")

    assert _apply_patches_to_workdir(str(repo), patches) == []
    assert (repo / "b.txt").read_text() == "local\n"


def test_git_am_keeps_configured_identity(repo):
    patches = _dirty_patches(repo)
    _git(repo, "config", "user.name", "Configured Person")
    _git(repo, "config", "user.email", "configured@example.com")

    assert _apply_patches_to_workdir(str(repo), patches) == []
    committer = _git(repo, "log", "-1", "--format=%cn <%ce>").strip()
    assert committer == "Configured Person <configured@example.com>"
