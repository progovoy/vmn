"""Backends are opened once per repo per command, and `vmn show` changes nothing."""
import os

import git

from helpers import _configure_2_deps, _init_app, _run_vmn_init, _show, _stamp_app
from island_helpers import _commit, _out
from version_stamp.backends import factory
from version_stamp.backends.git import GitBackend
from version_stamp.cli.entry import vmn_run
from version_stamp.core.constants import VMN_BE_TYPE_GIT
from version_stamp.core.logging import reset_logger


def _stamped_repo(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    return params


def _move_branch_behind_head(repo):
    """Detach HEAD (already pushed) so that no local branch contains it."""
    branch = _out(repo, "branch", "--show-current")
    _out(repo, "checkout", "-q", "--detach")
    _out(repo, "branch", "-q", "-f", branch, "HEAD~1")
    return branch


def _detach_past_local_branches(repo):
    branch = _out(repo, "branch", "--show-current")
    _commit(repo, "detached.txt")
    _out(repo, "push", "-q", "origin", branch)
    return _move_branch_behind_head(repo)


def _repo_state(repo):
    return _out(repo, "branch", "-a"), _out(repo, "rev-parse", "HEAD"), _out(
        repo, "status", "--porcelain", "--branch"
    )


def test_get_client_opens_the_repo_once(app_layout, monkeypatch):
    opened = []
    original = git.Repo.__init__

    def counting_init(self, *args, **kwargs):
        opened.append(args)
        original(self, *args, **kwargs)

    monkeypatch.setattr(git.Repo, "__init__", counting_init)

    be, err = factory.get_client(app_layout.repo_path, VMN_BE_TYPE_GIT)

    assert err is None
    assert len(opened) == 1
    del be


def test_get_client_reports_a_non_git_dir(tmp_path):
    be, err = factory.get_client(str(tmp_path), VMN_BE_TYPE_GIT)

    assert be is None
    assert "is not a functional git" in err


def test_read_only_backend_reports_remote_branch_without_creating_one(app_layout):
    _stamped_repo(app_layout)
    repo = app_layout.repo_path
    branch = _detach_past_local_branches(repo)
    before = _repo_state(repo)

    backend = GitBackend(repo, read_only=True)

    assert _repo_state(repo) == before
    assert backend.active_branch == branch
    assert backend.remote_active_branch == f"origin/{branch}"
    assert backend.in_detached_head()


def test_show_on_detached_repo_has_no_side_effects(app_layout, capfd):
    _stamped_repo(app_layout)
    repo = app_layout.repo_path
    _move_branch_behind_head(repo)
    before = _repo_state(repo)

    capfd.readouterr()
    assert _show(app_layout.app_name) == 0

    assert capfd.readouterr().out == "0.0.1\n"
    assert _repo_state(repo) == before


def test_show_on_detached_dep_has_no_side_effects(app_layout, capfd):
    params = _stamped_repo(app_layout)
    _configure_2_deps(app_layout, params)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    dep = app_layout._repos["repo1"]["path"]
    _move_branch_behind_head(dep)
    before = _repo_state(dep)
    main_before = _repo_state(app_layout.repo_path)

    capfd.readouterr()
    assert _show(app_layout.app_name) == 0

    assert capfd.readouterr().out == "0.0.2\n"
    assert _repo_state(dep) == before
    assert _repo_state(app_layout.repo_path) == main_before


def test_stamp_builds_each_dep_backend_once(app_layout, monkeypatch):
    params = _stamped_repo(app_layout)
    _configure_2_deps(app_layout, params)
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")

    built = []
    original = GitBackend.__init__

    def counting_init(self, repo_path, *args, **kwargs):
        built.append(repo_path)
        original(self, repo_path, *args, **kwargs)

    monkeypatch.setattr(GitBackend, "__init__", counting_init)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    for dep in ("repo1", "repo2"):
        dep_builds = [p for p in built if p.rstrip("/").endswith(dep)]
        assert len(dep_builds) == 1, (dep, built)


def _stamper(app_name):
    reset_logger()
    return vmn_run(["show", app_name])[1].vcs


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def test_files_to_add_to_index_are_the_changed_version_files(app_layout, monkeypatch):
    _stamped_repo(app_layout)
    repo = app_layout.repo_path
    vcs = _stamper(app_layout.app_name)
    modified = os.path.join(repo, "a", "modified.txt")
    untracked = os.path.join(repo, "a", "new_version.txt")
    clean = os.path.join(repo, "a", "clean.txt")
    for path in (modified, clean):
        _write(path, "v0")
        _out(repo, "add", path)
    _out(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "x")
    _write(modified, "v1")
    _write(untracked, "new")
    _write(os.path.join(repo, "unrelated.txt"), "new")

    commands = []
    original = git.cmd.Git.execute

    def recording_execute(self, command, *args, **kwargs):
        commands.append(list(command))
        return original(self, command, *args, **kwargs)

    monkeypatch.setattr(git.cmd.Git, "execute", recording_execute)

    files = vcs.get_files_to_add_to_index([modified, untracked, clean])

    assert files == [modified, untracked]
    status_calls = [c for c in commands if "status" in c]
    assert len(status_calls) == 1
    pathspec = status_calls[0][status_calls[0].index("--") + 1 :]
    assert pathspec == [
        os.path.join("a", "modified.txt"),
        os.path.join("a", "new_version.txt"),
        os.path.join("a", "clean.txt"),
    ]
