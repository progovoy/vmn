"""GitBackend branch lookups for a commit."""
import subprocess

from helpers import _init_app, _run_vmn_init, _stamp_app
from island_helpers import _commit, _out
from version_stamp.backends.git import GitBackend


def _stamped_repo(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    return app_layout.repo_path


def _add_other_remote(repo, tmp_path, name, refspec):
    other = str(tmp_path / f"{name}.git")
    subprocess.run(["git", "init", "-q", "--bare", other], check=True)
    _out(repo, "remote", "add", name, other)
    _out(repo, "push", "-q", name, refspec)
    _out(repo, "fetch", "-q", name)


def _local_branches(repo):
    return _out(repo, "branch", "--format=%(refname:short)").split()


def test_branches_containing_lists_local_and_selected_remote_branches(
    app_layout, tmp_path
):
    repo = _stamped_repo(app_layout)
    default = _out(repo, "branch", "--show-current")
    head = _out(repo, "rev-parse", "HEAD")
    _out(repo, "branch", "aaa")
    _out(repo, "push", "-q", "origin", "HEAD:refs/heads/remote-only")
    _add_other_remote(repo, tmp_path, "other", "HEAD:refs/heads/other-only")
    backend = GitBackend(repo)
    branches_before = _local_branches(repo)

    branches = backend.branches_containing(head)

    assert set(branches) == {default, "aaa", "remote-only"}
    assert _local_branches(repo) == branches_before
    assert backend.active_branch == default


def test_detached_head_picks_branch_of_selected_remote(app_layout, tmp_path):
    repo = _stamped_repo(app_layout)
    default = _out(repo, "branch", "--show-current")
    _out(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "feature.txt")
    _out(repo, "push", "-q", "origin", "feature")
    _add_other_remote(repo, tmp_path, "aaa", "HEAD:refs/heads/x")
    _out(repo, "checkout", "-q", "--detach")
    _out(repo, "branch", "-q", "-D", "feature")
    assert default not in _out(repo, "branch", "--contains", "HEAD")

    backend = GitBackend(repo)

    assert backend.active_branch.startswith("vmn_tracking_remote__origin_feature__")
    assert backend.remote_active_branch == "origin/feature"
