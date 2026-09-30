"""GitBackend fetches and the git execute logging patch."""
import git
import pytest

from helpers import _init_app, _run_vmn_init, _show, _stamp_app
from island_helpers import _out
from version_stamp.backends.git import GitBackend


def test_clone_failure_keeps_git_stderr(tmp_path):
    with pytest.raises(git.exc.GitCommandError) as exc_info:
        GitBackend.clone(tmp_path / "dst", tmp_path / "no_such_repo")

    assert "fatal:" in str(exc_info.value)
    assert "does not exist" in exc_info.value.stderr


def test_explicit_no_extended_output_returns_stdout(app_layout):
    repo = git.Repo(app_layout.repo_path)

    ret = repo.git.execute(["git", "rev-parse", "HEAD"], with_extended_output=False)

    assert ret == _out(app_layout.repo_path, "rev-parse", "HEAD")


def test_show_in_shallow_clone_without_remote(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    clone = app_layout.create_new_clone("test_repo_0", depth=1)
    _out(clone, "remote", "remove", "origin")
    app_layout.set_working_dir(clone)
    capfd.readouterr()

    assert _show(app_layout.app_name) == 0

    assert "0.0.1" in capfd.readouterr().out


def _shallow_clone_on_non_default_remote(app_layout):
    """A shallow clone whose only real remote is not git's default ``origin``."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "one")
    clone = app_layout.create_new_clone("test_repo_0", depth=1)
    _out(clone, "remote", "rename", "origin", "upstream")
    _out(clone, "branch", "--unset-upstream")
    _out(clone, "remote", "add", "zzz", "/nonexistent/zzz")
    return clone


def test_cached_fetch_targets_selected_remote(app_layout):
    clone = _shallow_clone_on_non_default_remote(app_layout)
    _out(app_layout.repo_path, "tag", "-a", "late_tag", "-m", "late")
    _out(app_layout.repo_path, "push", "-q", "origin", "late_tag")
    backend = GitBackend(clone)
    assert backend.selected_remote.name == "upstream"

    backend.perform_cached_fetch(force=True)

    assert "late_tag" in _out(clone, "tag").split()


def test_commit_range_unshallows_from_selected_remote(app_layout):
    clone = _shallow_clone_on_non_default_remote(app_layout)
    _out(clone, "fetch", "-q", "--depth=1", "upstream", "tag", "test_app_0.0.1")
    backend = GitBackend(clone)
    assert _out(clone, "rev-parse", "--is-shallow-repository") == "true"

    list(backend.get_commits_range_iter("test_app_0.0.1"))

    assert _out(clone, "rev-parse", "--is-shallow-repository") == "false"
