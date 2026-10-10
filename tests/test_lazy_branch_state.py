"""A backend resolves its branch on first use, once per command (plan 17 F3/F4/F10)."""
import git
import pytest
from helpers import _stamp_app
from island_helpers import (  # noqa: F401
    _ci_checkout,
    _no_ci_env,
    _out,
    _stamped_repo,
)
from version_stamp.backends.git import GitBackend
from version_stamp.core.logging import reset_logger


@pytest.fixture
def git_commands(monkeypatch):
    """Every git command (argv list) run through GitPython from now on."""
    commands = []
    original = git.cmd.Git.execute

    def recording_execute(self, command, *args, **kwargs):
        commands.append([str(part) for part in command])
        return original(self, command, *args, **kwargs)

    monkeypatch.setattr(git.cmd.Git, "execute", recording_execute)
    return commands


def _branch_lookups(commands):
    """Commands that resolve a branch: containment, reflog, upstream."""
    return [
        c
        for c in commands
        if "--contains" in c
        or c[1:3] == ["log", "-g"]
        or any(part.endswith("@{u}") for part in c)
    ]


def _contains_lookups(commands):
    return [c for c in commands if c[1:2] == ["for-each-ref"] and "--contains" in c]


def test_detached_backend_resolves_nothing_until_its_branch_is_read(
    app_layout, git_commands
):
    repo, default, _ = _stamped_repo(app_layout)
    _ci_checkout(repo, default)
    git_commands.clear()

    backend = GitBackend(repo)
    assert backend.in_detached_head()

    assert _branch_lookups(git_commands) == []
    assert backend.active_branch == default
    assert backend.remote_active_branch == f"origin/{default}"
    assert _contains_lookups(git_commands)


def test_attached_backend_looks_its_upstream_up_on_first_read(
    app_layout, git_commands
):
    repo, default, _ = _stamped_repo(app_layout)
    git_commands.clear()

    backend = GitBackend(repo)

    assert _branch_lookups(git_commands) == []
    assert backend.active_branch == default
    assert backend.remote_active_branch == f"origin/{default}"
    assert backend.active_branch_is_local


def test_branch_read_after_a_detached_move_reports_the_construction_state(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _ci_checkout(repo, default)
    expected = GitBackend(repo)
    expected = (expected.active_branch, expected.remote_active_branch)
    backend = GitBackend(repo)

    backend.checkout(rev=_out(repo, "rev-parse", "HEAD~1"))

    assert (backend.active_branch, backend.remote_active_branch) == expected


def test_branch_read_after_leaving_a_branch_reports_the_construction_state(
    app_layout,
):
    repo, default, _ = _stamped_repo(app_layout)
    backend = GitBackend(repo)

    backend.checkout(rev=_out(repo, "rev-parse", "HEAD~1"))

    assert backend.active_branch == default
    assert backend.remote_active_branch == f"origin/{default}"
    assert backend.active_branch_is_local


def test_assigned_branch_state_wins(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    backend = GitBackend(repo)

    backend.remote_active_branch = "origin/elsewhere"

    assert backend.active_branch == default
    assert backend.remote_active_branch == "origin/elsewhere"


def test_ci_stamp_looks_up_branches_containing_head_once(app_layout, git_commands):
    repo, default, _ = _stamped_repo(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    _ci_checkout(repo, default)
    git_commands.clear()

    reset_logger()
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    assert _out(repo, "branch", "--show-current") == default
    assert len(_contains_lookups(git_commands)) == 1


def test_checkout_branch_reports_success_as_a_bool(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    backend = GitBackend(repo)

    assert backend.checkout_branch(default) is True
    assert backend.checkout_branch("no-such-branch") is False
