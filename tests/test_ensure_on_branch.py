"""ensure_on_branch (plan 17 §4): real branch names, legacy fallbacks, cleanup."""

import os

import pytest
from helpers import _goto, _init_app, _run_vmn_init, _stamp_app
from island_helpers import _commit, _out
from version_stamp.backends.branch_resolver import CI_BRANCH_ENV_VARS
from version_stamp.backends.git import GitBackend

LEGACY = "vmn_tracking_remote__"


@pytest.fixture(autouse=True)
def _no_ci_env(monkeypatch):
    for name in (*CI_BRANCH_ENV_VARS, "GITHUB_REF_TYPE"):
        monkeypatch.delenv(name, raising=False)


def _stamped_repo(app_layout):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    repo = app_layout.repo_path
    return repo, _out(repo, "branch", "--show-current"), params


def _branches(repo):
    return _out(
        repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/"
    ).split()


def _head(repo):
    return _out(repo, "rev-parse", "HEAD")


def _current(repo):
    return _out(repo, "branch", "--show-current")


def _ci_checkout(repo, default, rev="HEAD"):
    _out(repo, "checkout", "-q", "-f", _out(repo, "rev-parse", rev))
    _out(repo, "branch", "-q", "-D", default)


def _push_head_as(repo, name):
    _out(repo, "push", "-q", "origin", f"HEAD:refs/heads/{name}")
    _out(repo, "fetch", "-q", "origin")


def _stamp_ensure(repo):
    return GitBackend(repo).ensure_on_branch(require_tip=True, use_ci_hint=True)


def test_ci_checkout_at_remote_tip_lands_on_the_real_branch(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _ci_checkout(repo, default)
    head = _head(repo)
    backend = GitBackend(repo)

    assert backend.ensure_on_branch(require_tip=True, use_ci_hint=True)

    assert (_current(repo), _head(repo)) == (default, head)
    assert _out(repo, "rev-parse", "--abbrev-ref", f"{default}@{{u}}") == (
        f"origin/{default}"
    )
    assert not [b for b in _branches(repo) if b.startswith(LEGACY)]
    assert backend.active_branch == default
    assert backend.remote_active_branch == f"origin/{default}"
    assert not backend.detached_head


def test_local_branch_behind_is_fast_forwarded(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    head = _head(repo)
    _out(repo, "checkout", "-q", "--detach")
    _out(repo, "branch", "-q", "-f", default, "HEAD~1")

    assert _stamp_ensure(repo)

    assert (_current(repo), _head(repo)) == (default, head)


def test_diverged_local_branch_falls_back_to_the_legacy_branch(app_layout, capfd):
    repo, default, _ = _stamped_repo(app_layout)
    head = _head(repo)
    _out(repo, "checkout", "-q", "--detach")
    _out(repo, "branch", "-q", "-f", default, "HEAD~1")
    _out(repo, "checkout", "-q", default)
    _commit(repo, "local.txt")
    local_tip = _head(repo)
    _out(repo, "checkout", "-q", head)
    capfd.readouterr()

    assert _stamp_ensure(repo)

    assert _current(repo) == f"{LEGACY}origin_{default}__from_{head[:5]}"
    assert _head(repo) == head
    assert _out(repo, "rev-parse", default) == local_tip
    out, err = capfd.readouterr()
    assert "[WARNING]" in out + err and default in out + err


def test_local_branch_containing_head_keeps_head_detached(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _out(repo, "checkout", "-q", "--detach")
    before = _branches(repo)

    assert not _stamp_ensure(repo)

    assert _current(repo) == "" and _branches(repo) == before


def test_head_that_is_no_remote_tip_stays_detached(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _ci_checkout(repo, default, rev="HEAD~1")

    assert not _stamp_ensure(repo)

    assert _current(repo) == "" and _branches(repo) == []


def test_on_a_branch_is_a_noop(app_layout):
    repo, default, _ = _stamped_repo(app_layout)

    assert _stamp_ensure(repo)

    assert _current(repo) == default


def test_ambiguous_tips_take_the_alphabetical_pick_and_warn(app_layout, capfd):
    repo, default, _ = _stamped_repo(app_layout)
    _push_head_as(repo, "aaa")
    _ci_checkout(repo, default)
    capfd.readouterr()

    assert _stamp_ensure(repo)

    assert _current(repo) == min("aaa", default)
    out, err = capfd.readouterr()
    assert "[WARNING]" in out + err
    assert "aaa" in out + err and default in out + err


def test_ci_hint_picks_the_branch_to_stamp(app_layout, monkeypatch):
    repo, default, _ = _stamped_repo(app_layout)
    _push_head_as(repo, "release/1.2")
    _ci_checkout(repo, default)
    monkeypatch.setenv("BRANCH_NAME", "release/1.2")

    assert _stamp_ensure(repo)

    assert _current(repo) == "release/1.2"


def test_goto_mode_checks_out_the_remote_branch_tip(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    tip = _head(repo)
    _ci_checkout(repo, default, rev="HEAD~1")

    assert GitBackend(repo).ensure_on_branch(require_tip=False, use_ci_hint=False)

    assert (_current(repo), _head(repo)) == (default, tip)


def test_goto_mode_returns_to_the_branch_you_left(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _out(repo, "branch", "aaa")
    _out(repo, "checkout", "-q", "-b", "feature")
    _out(repo, "checkout", "-q", "HEAD~1")

    assert GitBackend(repo).ensure_on_branch(require_tip=False, use_ci_hint=False)

    assert _current(repo) == "feature"


def test_stale_legacy_branches_are_deleted(app_layout, tmp_path):
    repo, default, _ = _stamped_repo(app_layout)
    merged = f"{LEGACY}origin_x__from_11111"
    ahead = f"{LEGACY}origin_y__from_22222"
    in_worktree = f"{LEGACY}origin_z__from_33333"
    current = f"{LEGACY}origin_{default}__from_44444"
    _out(repo, "branch", "-q", "--track", merged, f"origin/{default}")
    _out(repo, "branch", "-q", "-f", merged, "HEAD~1")
    _out(repo, "branch", "-q", "--track", in_worktree, f"origin/{default}")
    _out(repo, "worktree", "add", "-q", str(tmp_path / "wt"), in_worktree)
    _out(repo, "checkout", "-q", "-b", ahead, "--track", f"origin/{default}")
    _commit(repo, "ahead.txt")
    _out(repo, "checkout", "-q", "-b", current, "--track", f"origin/{default}")

    assert _stamp_ensure(repo)

    left = _branches(repo)
    assert merged not in left
    assert {ahead, in_worktree, current, default} <= set(left)


def test_goto_back_from_a_ci_checkout_lands_on_the_real_branch(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _ci_checkout(repo, default)

    assert _goto(app_layout.app_name) == 0

    assert _current(repo) == default
    assert not [b for b in _branches(repo) if b.startswith(LEGACY)]


def _branch_conf(app_layout, params, default):
    path = os.path.join(
        os.path.dirname(params["app_conf_path"]), "branch_conf", default, "conf.yml"
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    app_layout.write_conf(
        path,
        template="[{major}][.{minor}]",
        policies={"whitelist_release_branches": [default]},
    )
    return os.path.relpath(path, app_layout.repo_path)


def _assert_stamped_with_branch_conf(app_layout, capfd, repo, default, conf):
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")

    assert err == 0
    assert "[INFO] 0.0\n" in capfd.readouterr().out
    assert conf in _out(repo, "ls-tree", "-r", "--name-only", "HEAD").split()
    assert ver_info["stamping"]["app"]["stamped_on_branch"] == default
    assert _out(repo, "rev-parse", f"origin/{default}") == _head(repo)


def test_ci_stamp_keeps_and_applies_the_branch_conf(app_layout, capfd):
    repo, default, params = _stamped_repo(app_layout)
    conf = _branch_conf(app_layout, params, default)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    _ci_checkout(repo, default)

    _assert_stamped_with_branch_conf(app_layout, capfd, repo, default, conf)

    assert _current(repo) == default
    assert not [b for b in _branches(repo) if b.startswith(LEGACY)]


def test_stamp_on_a_legacy_branch_uses_its_upstream_identity(app_layout, capfd):
    repo, default, params = _stamped_repo(app_layout)
    conf = _branch_conf(app_layout, params, default)
    legacy = f"{LEGACY}origin_{default}__from_abcde"
    _out(repo, "checkout", "-q", "-b", legacy, "--track", f"origin/{default}")
    _commit(repo, "f1.file")
    _out(repo, "push", "-q", "origin", f"HEAD:refs/heads/{default}")

    _assert_stamped_with_branch_conf(app_layout, capfd, repo, default, conf)

    assert _current(repo) == legacy
