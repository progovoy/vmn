"""vmn must never push through the wrong remote or to another branch."""
import subprocess

from helpers import _init_app, _run_vmn_init, _stamp_app
from island_helpers import _commit, _out
from version_stamp.backends.git import GitBackend
from version_stamp.core.constants import VMN_READONLY_REMOTE


def _remote_out(remote, *args):
    return subprocess.check_output(["git", "--git-dir", remote, *args], text=True).strip()


def _remote_branches(remote):
    return _remote_out(remote, "branch", "--format=%(refname:short)").split()


def _stamped_repo(app_layout):
    from pathlib import Path

    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    repo = Path(app_layout.repo_path)
    _commit(repo, "unstamped.txt")
    _out(repo, "push", "-q")
    return repo, _out(repo, "branch", "--show-current")


def test_new_branch_without_remote_counterpart_is_not_pushed_to_default_branch(
    app_layout, capfd
):
    repo, default = _stamped_repo(app_layout)
    remote = app_layout.test_app_remote
    default_before = _remote_out(remote, "rev-parse", default)
    _out(repo, "checkout", "-q", "-b", "feature/x")
    capfd.readouterr()

    assert _stamp_app(app_layout.app_name, "patch")[0] == 1

    assert "git push -u origin feature/x" in capfd.readouterr().err
    assert _remote_out(remote, "rev-parse", default) == default_before
    assert "feature/x" not in _remote_branches(remote)


def test_published_new_branch_stamps_onto_its_own_remote_branch(app_layout):
    repo, default = _stamped_repo(app_layout)
    remote = app_layout.test_app_remote
    default_before = _remote_out(remote, "rev-parse", default)
    _out(repo, "checkout", "-q", "-b", "feature/x")
    _commit(repo, "feature.txt")
    _out(repo, "push", "-q", "-u", "origin", "feature/x")

    assert _stamp_app(app_layout.app_name, "patch")[0] == 0

    assert _remote_out(remote, "rev-parse", default) == default_before
    assert _out(repo, "rev-parse", "feature/x") == _remote_out(
        remote, "rev-parse", "feature/x"
    )


def test_branch_tracking_readonly_remote_is_never_pushed_to_it(app_layout, capfd):
    repo, default = _stamped_repo(app_layout)
    remote = app_layout.test_app_remote
    default_before = _remote_out(remote, "rev-parse", default)
    _out(repo, "remote", "add", VMN_READONLY_REMOTE, remote)
    _out(repo, "fetch", "-q", VMN_READONLY_REMOTE)
    _out(repo, "checkout", "-q", "-b", "feature/z", f"{VMN_READONLY_REMOTE}/{default}")
    _commit(repo, "z.txt")
    capfd.readouterr()

    assert _stamp_app(app_layout.app_name, "patch")[0] == 1

    assert "git push -u origin feature/z" in capfd.readouterr().err
    assert _remote_out(remote, "rev-parse", default) == default_before
    assert all(b.startswith("feature") or b == default for b in _remote_branches(remote))

    _out(repo, "push", "-q", "-u", "origin", "feature/z")
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    assert _out(repo, "rev-parse", "--abbrev-ref", "feature/z@{u}") == "origin/feature/z"


def test_readonly_remote_is_never_selected(app_layout):
    _run_vmn_init()
    repo_path = app_layout.repo_path
    url = _out(repo_path, "remote", "get-url", "origin")
    _out(repo_path, "remote", "remove", "origin")
    _out(repo_path, "remote", "add", VMN_READONLY_REMOTE, url)
    _out(repo_path, "remote", "add", "origin", url)

    backend = GitBackend(repo_path)

    assert [r.name for r in backend._be.remotes][0] == VMN_READONLY_REMOTE

    assert backend.selected_remote.name == "origin"
