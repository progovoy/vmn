"""goto / stamp / release / add from detached (CI-style) checkouts (plan 17 §4)."""

import pytest
from helpers import (
    _add_buildmetadata_to_version,
    _configure_2_deps,
    _goto,
    _release_app,
    _stamp_app,
)
from island_helpers import _commit, _out
from test_ensure_on_branch import (
    LEGACY,
    _branches,
    _ci_checkout,
    _current,
    _head,
    _push_head_as,
    _stamped_repo,
)
from version_stamp.backends.branch_resolver import CI_BRANCH_ENV_VARS


@pytest.fixture(autouse=True)
def _no_ci_env(monkeypatch):
    for name in (*CI_BRANCH_ENV_VARS, "GITHUB_REF_TYPE"):
        monkeypatch.delenv(name, raising=False)


def _remote_tags(repo):
    return {
        line.split()[1]
        for line in _out(repo, "ls-remote", "--tags", "origin").splitlines()
        if not line.endswith("^{}")
    }


def _no_legacy(repo):
    return not [b for b in _branches(repo) if b.startswith(LEGACY)]


def test_goto_version_from_a_ci_checkout_creates_no_branch(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    first = _head(repo)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    _ci_checkout(repo, default)

    assert _goto(app_layout.app_name, version="0.0.1") == 0

    assert _branches(repo) == []
    assert (_current(repo), _head(repo)) == ("", first)


def test_goto_back_from_a_ci_checkout_tracks_the_remote_tip(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    tip = _head(repo)
    _ci_checkout(repo, default, rev="HEAD~1")

    assert _goto(app_layout.app_name) == 0

    assert (_current(repo), _head(repo)) == (default, tip)
    assert _out(repo, "rev-parse", "--abbrev-ref", f"{default}@{{u}}") == (
        f"origin/{default}"
    )
    assert _no_legacy(repo)


def test_goto_back_returns_to_the_branch_goto_left(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _out(repo, "branch", "aws/prod")
    _out(repo, "checkout", "-q", "-b", "feature/x")
    _out(repo, "push", "-q", "-u", "origin", "feature/x")

    assert _goto(app_layout.app_name, version="0.0.1") == 0
    assert _current(repo) == ""
    assert _goto(app_layout.app_name) == 0

    assert _current(repo) == "feature/x"


def test_goto_back_uses_the_branch_the_head_version_was_stamped_on(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _out(repo, "checkout", "-q", "-b", "rel")
    _out(repo, "push", "-q", "-u", "origin", "rel")
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    version_commit = _head(repo)
    _push_head_as(repo, "aaa")
    _commit(repo, "after.txt")
    for name in ("rel", "aaa"):
        _out(repo, "push", "-q", "-f", "origin", f"HEAD:refs/heads/{name}")
    _out(repo, "checkout", "-q", "-f", version_commit)
    _out(repo, "branch", "-q", "-D", "rel", default)

    assert _goto(app_layout.app_name) == 0

    assert _current(repo) == "rel"


def test_unpinned_dep_ignores_the_ci_branch_hint(app_layout, monkeypatch):
    _, _, params = _stamped_repo(app_layout)
    _configure_2_deps(app_layout, params)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    dep = app_layout._repos["repo1"]["path"]
    dep_default = _current(dep)
    _push_head_as(dep, "other")
    _out(dep, "checkout", "-q", "--detach")
    monkeypatch.setenv("BRANCH_NAME", "other")

    assert _goto(app_layout.app_name) == 0

    assert _current(dep) == dep_default


def test_release_and_add_from_a_detached_commit_push_only_tags(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "rc.file", "rc")
    assert _stamp_app(app_layout.app_name, "patch", prerelease="rc")[0] == 0
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    remote_tip = _out(repo, "rev-parse", f"origin/{default}")
    _ci_checkout(repo, default, rev="HEAD~1")
    tags_before = _remote_tags(repo)

    assert _release_app(app_layout.app_name, version="0.0.2-rc.1")[0] == 0
    assert _add_buildmetadata_to_version(app_layout, "build1", version="0.0.2") == 0

    new_tags = _remote_tags(repo) - tags_before
    name = app_layout.app_name
    assert new_tags == {f"refs/tags/{name}_0.0.2", f"refs/tags/{name}_0.0.2+build1"}
    assert _out(repo, "ls-remote", "origin", f"refs/heads/{default}").split()[0] == (
        remote_tip
    )
    assert _current(repo) == "" and _branches(repo) == []


def test_release_stamp_from_a_ci_checkout_lands_on_the_real_branch(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "rc.file", "rc")
    assert _stamp_app(app_layout.app_name, "patch", prerelease="rc")[0] == 0
    _ci_checkout(repo, default)

    assert _release_app(app_layout.app_name, stamp=True)[0] == 0

    assert _current(repo) == default
    assert _no_legacy(repo)
    assert _out(repo, "rev-parse", f"origin/{default}") == _head(repo)


def test_stamp_in_detached_head_hints_the_checkout(app_layout, capfd):
    repo, default, _ = _stamped_repo(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    _out(repo, "checkout", "-q", "--detach")
    capfd.readouterr()

    assert _stamp_app(app_layout.app_name, "patch")[0] == 1

    captured = capfd.readouterr()
    assert "[ERROR] In detached head. Will not stamp new version" in captured.err
    assert f"git checkout {default}" in captured.out


def test_release_stamp_in_detached_head_hints_the_checkout(app_layout, capfd):
    repo, default, _ = _stamped_repo(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "rc.file", "rc")
    assert _stamp_app(app_layout.app_name, "patch", prerelease="rc")[0] == 0
    _out(repo, "checkout", "-q", "--detach")
    capfd.readouterr()

    assert _release_app(app_layout.app_name, stamp=True)[0] == 1

    captured = capfd.readouterr()
    assert captured.err == "[ERROR] Cannot use --stamp in detached HEAD state\n"
    assert f"git checkout {default}" in captured.out
