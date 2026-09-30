"""version_stamp.core.git_cmd: the shared git subprocess plumbing."""
import subprocess

from island_helpers import _commit, _git, _out
from version_stamp.core import git_cmd
from version_stamp.core.constants import VMN_READONLY_REMOTE
from version_stamp.core.logging import ensure_logger


def _repo(tmp_path, name="repo"):
    repo = tmp_path / name
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    return repo


def test_run_git_returns_bytes_by_default(tmp_path):
    repo = _repo(tmp_path)
    (repo / "latin1.txt").write_bytes(b"caf\xe9\n")
    _git(repo, "add", "latin1.txt")

    result = git_cmd.run_git(repo, ["diff", "--cached"])

    assert result.returncode == 0
    assert b"caf\xe9" in result.stdout


def test_run_git_text_mode_and_stdin(tmp_path):
    repo = _repo(tmp_path)

    result = git_cmd.run_git(repo, ["hash-object", "--stdin"], stdin="x\n", text=True)

    # sha1 of the blob "x\n"
    assert result.stdout.strip() == "587be6b4c3f93f93c489c0111bba5596147a26cb"


def test_run_git_timeout_is_none_not_a_raise(tmp_path, monkeypatch):
    def timeout(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    ensure_logger()
    monkeypatch.setattr(subprocess, "run", timeout)

    assert git_cmd.run_git(tmp_path, ["status"], timeout=1) is None
    assert git_cmd.git_ok(tmp_path, ["status"], timeout=1) is False
    assert git_cmd.git_stdout(tmp_path, ["status"], timeout=1) is None


def test_git_ok_and_git_stdout(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "a.txt")

    assert git_cmd.git_ok(repo, ["rev-parse", "HEAD"])
    assert not git_cmd.git_ok(repo, ["rev-parse", "no-such-ref"])
    assert git_cmd.git_stdout(repo, ["rev-parse", "HEAD"]) == _out(repo, "rev-parse", "HEAD")
    assert git_cmd.git_stdout(repo, ["rev-parse", "no-such-ref"]) is None


def test_primary_remote_skips_the_readonly_remote(tmp_path):
    repo = _repo(tmp_path)
    assert git_cmd.primary_remote(repo) is None
    assert git_cmd.remote_url(repo) is None

    _git(repo, "remote", "add", VMN_READONLY_REMOTE, "/readonly/url")
    _git(repo, "remote", "add", "upstream", "/upstream/url")

    assert git_cmd.primary_remote(repo) == "upstream"
    assert git_cmd.remote_url(repo) == "/upstream/url"


def _bare_with_two_commits(tmp_path):
    source = _repo(tmp_path, "source")
    _commit(source, "first.txt")
    first = _out(source, "rev-parse", "HEAD")
    _commit(source, "second.txt")
    remote = tmp_path / "source.git"
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(source), str(remote)], check=True
    )
    return f"file://{remote}", first


def test_clone_at_commit_detached_at_a_non_tip_commit(tmp_path):
    remote, first = _bare_with_two_commits(tmp_path)
    dest = tmp_path / "dest"

    assert git_cmd.clone_at_commit(dest, remote, first) == 0

    assert _out(dest, "rev-parse", "HEAD") == first
    assert _out(dest, "branch", "--show-current") == ""
    assert _out(dest, "remote", "get-url", "origin") == remote


def test_clone_at_commit_on_a_new_branch(tmp_path):
    remote, first = _bare_with_two_commits(tmp_path)
    dest = tmp_path / "dest"

    assert git_cmd.clone_at_commit(dest, remote, first, new_branch="island/x/main") == 0

    assert _out(dest, "rev-parse", "HEAD") == first
    assert _out(dest, "branch", "--show-current") == "island/x/main"


def test_clone_at_commit_without_commit_takes_the_branch_tip(tmp_path):
    remote, first = _bare_with_two_commits(tmp_path)
    dest = tmp_path / "dest"

    assert git_cmd.clone_at_commit(dest, remote, None, branch="main") == 0

    assert _out(dest, "rev-parse", "HEAD") != first
    assert _out(dest, "log", "--format=%s", "-1") == "second.txt"


def test_clone_at_commit_fails_on_unreachable_remote(tmp_path):
    ensure_logger()
    dest = tmp_path / "dest"

    assert git_cmd.clone_at_commit(dest, str(tmp_path / "missing.git"), "a" * 40) == 1
