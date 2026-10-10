"""Which branch a detached HEAD belongs to (plan 17 §3), with no side effects."""

import pytest
from island_helpers import (  # noqa: F401 (_no_ci_env is an autouse fixture)
    _branches,
    _ci_checkout,
    _commit,
    _no_ci_env,
    _out,
    _push_head_as,
    _stamped_repo,
)
from version_stamp.backends.git import GitBackend


def test_ci_checkout_resolves_the_remote_branch_without_creating_one(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _ci_checkout(repo, default)
    before = (_branches(repo), _out(repo, "rev-parse", "HEAD"))

    backend = GitBackend(repo)

    assert (_branches(repo), _out(repo, "rev-parse", "HEAD")) == before
    assert backend.active_branch == default
    assert backend.remote_active_branch == f"origin/{default}"
    assert backend.in_detached_head()


@pytest.mark.parametrize(
    "var,value",
    [
        ("BRANCH_NAME", "release/1.2"),
        ("GIT_BRANCH", "origin/release/1.2"),
        ("CI_COMMIT_REF_NAME", "release/1.2"),
        ("GITHUB_HEAD_REF", "release/1.2"),
    ],
)
def test_ci_hint_picks_among_tips(app_layout, monkeypatch, var, value):
    repo, default, _ = _stamped_repo(app_layout)
    _push_head_as(repo, "release/1.2")
    _ci_checkout(repo, default)
    monkeypatch.setenv(var, value)

    assert GitBackend(repo, use_ci_hint=True).active_branch == "release/1.2"


def test_github_ref_name_counts_only_for_branch_refs(app_layout, monkeypatch):
    repo, default, _ = _stamped_repo(app_layout)
    _push_head_as(repo, "zzz")
    _ci_checkout(repo, default)
    monkeypatch.setenv("GITHUB_REF_NAME", "zzz")
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    assert GitBackend(repo, use_ci_hint=True).active_branch == default

    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    assert GitBackend(repo, use_ci_hint=True).active_branch == "zzz"


def test_ci_hint_is_ignored_for_deps_and_when_it_does_not_qualify(
    app_layout, monkeypatch
):
    repo, default, _ = _stamped_repo(app_layout)
    _push_head_as(repo, "zzz")
    _ci_checkout(repo, default)
    monkeypatch.setenv("BRANCH_NAME", "zzz")
    assert GitBackend(repo).active_branch == default

    monkeypatch.setenv("BRANCH_NAME", "no-such-branch")
    assert GitBackend(repo, use_ci_hint=True).active_branch == default


def test_last_branch_from_reflog_beats_alphabetical(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _out(repo, "branch", "aaa")
    _out(repo, "checkout", "-q", "-b", "feature")
    _out(repo, "checkout", "-q", "--detach")
    _out(repo, "checkout", "-q", "HEAD~1")

    assert GitBackend(repo).active_branch == "feature"


def test_reflog_branch_not_containing_head_falls_through_to_tip_match(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    head = _out(repo, "rev-parse", "HEAD")
    _out(repo, "checkout", "-q", "-b", "aaa")
    _commit(repo, "ahead.txt")
    _out(repo, "checkout", "-q", "-b", "zzz", f"{head}~1")
    _out(repo, "checkout", "-q", head)

    assert GitBackend(repo).active_branch == default


def test_stamping_branch_decides_between_containers(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    head = _out(repo, "rev-parse", "HEAD")
    for name in ("aaa", "bbb"):
        _out(repo, "checkout", "-q", "-b", name, head)
        _commit(repo, f"{name}.txt")
    _out(repo, "update-ref", f"refs/remotes/origin/{default}", "aaa")
    _out(repo, "checkout", "-q", "-b", "zzz", f"{head}~1")
    _out(repo, "checkout", "-q", head)
    _out(repo, "branch", "-q", "-D", default)
    backend = GitBackend(repo)

    choice = backend.resolve_branch(head, version_branch=f"origin/{default}")
    assert choice.name == default
    assert backend.resolve_branch(head, version_branch="bbb").name == "bbb"
    assert backend.resolve_branch(head).rule == "legacy"


def test_unique_container(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _ci_checkout(repo, default, rev="HEAD~1")
    backend = GitBackend(repo)

    choice = backend.resolve_branch(_out(repo, "rev-parse", "HEAD"))

    assert (choice.name, choice.rule) == (default, "unique")


def test_ambiguous_falls_back_to_the_legacy_alphabetical_pick(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _push_head_as(repo, "aaa")
    _ci_checkout(repo, default)
    backend = GitBackend(repo)

    choice = backend.resolve_branch(_out(repo, "rev-parse", "HEAD"))

    assert choice.rule == "legacy"
    assert choice.name == min("aaa", default)
    assert set(choice.candidates) == {"aaa", default}


def test_require_tip_only_accepts_branches_whose_tip_is_head(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    head = _out(repo, "rev-parse", "HEAD")
    _push_head_as(repo, "feature")
    _commit(repo, "ahead.txt")
    _push_head_as(repo, "aaa")
    _ci_checkout(repo, default, rev=head)
    _out(
        repo, "update-ref", f"refs/remotes/origin/{default}", "refs/remotes/origin/aaa"
    )
    backend = GitBackend(repo)

    assert backend.resolve_branch(head, require_tip=True).name == "feature"
    _out(repo, "update-ref", "-d", "refs/remotes/origin/feature")
    assert backend.resolve_branch(head, require_tip=True) is None


def test_commit_no_branch_contains_does_not_raise(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _commit(repo, "orphan.txt")
    _out(repo, "checkout", "-q", "--detach")
    _out(repo, "branch", "-q", "-f", default, "HEAD~1")

    backend = GitBackend(repo)

    assert backend.active_branch is None
    assert backend.remote_active_branch is None
    assert backend.logical_branch() is None


def test_logical_branch_of_a_legacy_tracking_branch_is_its_upstream(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    legacy = f"vmn_tracking_remote__origin_{default}__from_abcde"
    _out(repo, "checkout", "-q", "-b", legacy, "--track", f"origin/{default}")

    backend = GitBackend(repo)

    assert backend.active_branch == legacy
    assert backend.logical_branch() == default
