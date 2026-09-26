import subprocess

import pytest

from version_stamp.cli import worktree_git as wg
from version_stamp.core.constants import VMN_READONLY_REMOTE


def _git(path, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=check
    )


def _out(path, *args):
    return _git(path, *args).stdout.strip()


def _commit(path, name):
    (path / name).write_text(name)
    _git(path, "add", name)
    _git(path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", name)


@pytest.fixture
def repos(tmp_path):
    """A bare remote, a clone `a`, and a second clone `other` used to push."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    a = tmp_path / "a"
    subprocess.run(["git", "clone", "-q", str(remote), str(a)], check=True)
    _git(a, "checkout", "-q", "-b", "main")
    _commit(a, "init")
    _git(a, "push", "-q", "-u", "origin", "main")
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    return remote, a, other


def _remote_refs(remote):
    return subprocess.check_output(
        ["git", "--git-dir", str(remote), "for-each-ref"], text=True
    )


def test_branch_upstream(repos):
    _, a, _ = repos
    _git(a, "branch", "local-only")

    assert wg.branch_upstream(a, "main") == "origin/main"
    assert wg.branch_upstream(a, "local-only") is None


def test_ensure_readonly_remote_mirrors_origin_without_push_or_refspecs(repos):
    remote, a, _ = repos

    assert wg.ensure_readonly_remote(a)
    assert wg.ensure_readonly_remote(a)

    assert _out(a, "remote", "get-url", VMN_READONLY_REMOTE) == str(remote)
    assert _out(a, "remote", "get-url", "--push", VMN_READONLY_REMOTE) == (
        wg.READONLY_PUSH_URL
    )
    fetch = _git(
        a, "config", "--get-all", f"remote.{VMN_READONLY_REMOTE}.fetch", check=False
    )
    assert fetch.stdout.strip() == ""


def test_ensure_readonly_remote_returns_false_without_origin(tmp_path):
    repo = tmp_path / "solo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    assert not wg.ensure_readonly_remote(repo)


def test_fetch_readonly_branch_fetches_only_named_branches(repos):
    remote, a, other = repos
    for branch in ("b", "c"):
        _git(other, "checkout", "-q", "-b", branch)
        _commit(other, branch)
        _git(other, "push", "-q", "origin", branch)
    wg.ensure_readonly_remote(a)

    assert wg.fetch_readonly_branch(a, "b")
    assert wg.fetch_readonly_branch(a, "b")

    refs = _out(a, "for-each-ref", "--format=%(refname)", "refs/remotes/vmn-readonly")
    assert refs.split() == ["refs/remotes/vmn-readonly/b"]
    fetch = _out(a, "config", "--get-all", f"remote.{VMN_READONLY_REMOTE}.fetch")
    assert fetch.splitlines() == [
        "+refs/heads/b:refs/remotes/vmn-readonly/b"
    ]
    assert not wg.fetch_readonly_branch(a, "missing")


def _private_branch(a, source="main"):
    wg.ensure_readonly_remote(a)
    wg.fetch_readonly_branch(a, source)
    _git(a, "branch", f"island/i/{source}", source)
    assert wg.track_privately(a, f"island/i/{source}", f"{VMN_READONLY_REMOTE}/{source}")
    _git(a, "checkout", "-q", f"island/i/{source}")
    _commit(a, "private-work")
    return f"island/i/{source}"


def test_private_branch_cannot_be_pushed_over_the_source_branch(repos):
    remote, a, _ = repos
    _private_branch(a)
    before = _remote_refs(remote)

    for cmd in (
        ["push"],
        ["-c", "push.default=upstream", "push"],
        ["-c", "push.default=matching", "push"],
        ["-c", "push.default=upstream", "push", "origin"],
    ):
        assert _git(a, *cmd, check=False).returncode != 0, cmd

    assert _remote_refs(remote) == before


def test_private_branch_can_still_pull_rebase(repos):
    _, a, other = repos
    branch = _private_branch(a)
    _commit(other, "upstream-work")
    _git(other, "push", "-q", "origin", "main")

    assert _git(a, "pull", "--rebase", check=False).returncode == 0

    log = _out(a, "log", "--format=%s", branch).split()
    assert log[:2] == ["private-work", "upstream-work"]


def test_plain_push_to_origin_publishes_private_name_but_not_source(repos):
    remote, a, _ = repos
    branch = _private_branch(a)
    main_before = _out(a, "rev-parse", "origin/main")

    assert _git(a, "push", "origin", branch, check=False).returncode == 0

    heads = subprocess.check_output(
        ["git", "--git-dir", str(remote), "rev-parse", "main"], text=True
    ).strip()
    assert heads == main_before


def test_remove_readonly_remote_if_unused_waits_for_last_island_branch(repos):
    _, a, _ = repos
    first = _private_branch(a)
    _git(a, "branch", "island/j/main", "main")
    _git(a, "checkout", "-q", "main")

    _git(a, "branch", "-D", first)
    wg.remove_readonly_remote_if_unused(a)
    assert wg.git_remote_url(a) and _out(a, "remote").split() == [
        "origin",
        VMN_READONLY_REMOTE,
    ]

    _git(a, "branch", "-D", "island/j/main")
    wg.remove_readonly_remote_if_unused(a)
    assert _out(a, "remote").split() == ["origin"]


def test_is_dirty(repos):
    _, a, _ = repos

    assert not wg.is_dirty(a)
    (a / "new.txt").write_text("x")
    assert wg.is_dirty(a)
