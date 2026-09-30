"""Git plumbing consolidation: bytes-safe carry, primary remote, outgoing state."""
import subprocess
from pathlib import Path

from island_helpers import _app_with_dep, _commit, _create_island, _git, _island_a, _out
from version_stamp.backends.git import GitBackend
from version_stamp.cli import worktree_git as wg
from version_stamp.core.constants import VMN_READONLY_REMOTE


def test_carry_changes_carries_a_latin1_tracked_edit(app_layout, tmp_path):
    _app_with_dep(app_layout)
    repo = Path(app_layout.repo_path)
    tracked = next(p for p in repo.iterdir() if p.is_file() and p.name != ".gitignore")
    tracked.write_bytes(b"caf\xe9 latin-1\n")

    rc, island = _create_island(app_layout, tmp_path, "latin", "--carry-changes")

    assert rc == 0
    assert (_island_a(app_layout, island) / tracked.name).read_bytes() == (
        b"caf\xe9 latin-1\n"
    )


def _repo_with_remotes(tmp_path, *remotes):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _commit(repo, "a.txt")
    for name, url in remotes:
        _git(repo, "remote", "add", name, url)
    return repo


def test_get_repo_details_skips_the_readonly_remote(tmp_path):
    repo = _repo_with_remotes(
        tmp_path, (VMN_READONLY_REMOTE, "/readonly/url"), ("upstream", "/upstream/url")
    )

    _, remote, _ = GitBackend.get_repo_details(str(repo))

    assert remote == "/upstream/url"


def test_island_remote_helpers_use_a_non_origin_remote(tmp_path):
    repo = _repo_with_remotes(tmp_path, ("upstream", "/upstream/url"))

    assert wg.git_remote_url(repo) == "/upstream/url"
    assert wg.ensure_readonly_remote(repo)
    assert _out(repo, "remote", "get-url", VMN_READONLY_REMOTE) == "/upstream/url"


def test_outgoing_change_state_tells_detached_from_outgoing(app_layout):
    backend = GitBackend(app_layout.repo_path)
    assert backend.outgoing_change_state() == (None, None)

    app_layout.write_file_commit_and_push("test_repo_0", "f.txt", "x", push=False)
    backend = GitBackend(app_layout.repo_path)
    kind, err = backend.outgoing_change_state()
    assert kind == "outgoing" and err == backend.check_for_outgoing_changes()

    _git(app_layout.repo_path, "checkout", "-q", "--detach")
    backend = GitBackend(app_layout.repo_path)
    kind, err = backend.outgoing_change_state()
    assert kind == "detached" and err == backend.check_for_outgoing_changes()
