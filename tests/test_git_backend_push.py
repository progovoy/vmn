"""GitBackend.push: branch name mapping and atomic branch + tag publishing."""
import os
import stat
import subprocess
from types import SimpleNamespace

import git
import pytest

from helpers import _init_app, _run_vmn_init, _stamp_app
from island_helpers import _commit, _out
from version_stamp.backends.git import GitBackend
from version_stamp.backends.git_ops import GitOpsMixin
from version_stamp.core.logging import init_stamp_logger


def _remote_out(remote, *args):
    return subprocess.check_output(["git", "--git-dir", remote, *args], text=True).strip()


def _remote_branches(remote):
    return _remote_out(remote, "branch", "--format=%(refname:short)").split()


def _remote_tags(remote):
    return _remote_out(remote, "tag").split()


def _reject_tags_hook(remote):
    hook = os.path.join(remote, "hooks", "pre-receive")
    with open(hook, "w") as f:
        f.write(
            "#!/bin/sh\n"
            "while read old new ref; do\n"
            '  case "$ref" in refs/tags/*) echo "no tags" >&2; exit 1;; esac\n'
            "done\n"
        )
    os.chmod(hook, os.stat(hook).st_mode | stat.S_IEXEC)


def _commit_and_tag(repo, tag):
    _commit(repo, f"{tag}.txt")
    _out(repo, "tag", "-a", tag, "-m", tag)
    return GitBackend(str(repo))


def _stamped(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    return app_layout.repo_path, app_layout.test_app_remote


def test_branch_containing_remote_name_pushes_to_same_branch(app_layout):
    repo, remote = _stamped(app_layout)
    _out(repo, "checkout", "-q", "-b", "fix-origin/foo")
    _commit(repo, "foo.txt")
    _out(repo, "push", "-q", "-u", "origin", "fix-origin/foo")

    assert _stamp_app(app_layout.app_name, "patch")[0] == 0

    assert "fix-foo" not in _remote_branches(remote)
    assert _out(repo, "rev-parse", "HEAD") == _remote_out(
        remote, "rev-parse", "fix-origin/foo"
    )


def test_update_remote_tracking_ref_uses_given_branch(app_layout):
    repo, _ = _stamped(app_layout)
    backend = GitBackend(repo)

    backend._update_remote_tracking_ref("other")

    assert _out(repo, "rev-parse", "refs/remotes/origin/other") == _out(
        repo, "rev-parse", "HEAD"
    )


def test_rejected_tag_leaves_remote_branch_untouched(app_layout):
    repo, remote = _stamped(app_layout)
    branch = _out(repo, "branch", "--show-current")
    before = _remote_out(remote, "rev-parse", branch)
    _reject_tags_hook(remote)
    backend = _commit_and_tag(repo, "extra_tag")

    with pytest.raises(RuntimeError):
        backend.push(["extra_tag"])

    assert _remote_out(remote, "rev-parse", branch) == before
    assert "extra_tag" not in _remote_tags(remote)


def test_push_falls_back_when_server_lacks_atomic(app_layout):
    repo, remote = _stamped(app_layout)
    branch = _out(repo, "branch", "--show-current")
    _remote_out(remote, "config", "receive.advertiseAtomic", "false")
    backend = _commit_and_tag(repo, "extra_tag")

    backend.push(["extra_tag"])

    assert _out(repo, "rev-parse", "HEAD") == _remote_out(remote, "rev-parse", branch)
    assert "extra_tag" in _remote_tags(remote)


def _record_pushes_hook(remote, log_path):
    hook = os.path.join(remote, "hooks", "pre-receive")
    with open(hook, "w") as f:
        f.write(
            "#!/bin/sh\n"
            f'echo "push opts=$GIT_PUSH_OPTION_COUNT" >> "{log_path}"\n'
            f'while read old new ref; do echo "$ref" >> "{log_path}"; done\n'
        )
    os.chmod(hook, os.stat(hook).st_mode | stat.S_IEXEC)


def test_push_sends_branch_and_tags_in_one_push_with_ci_skip(app_layout, tmp_path):
    repo, remote = _stamped(app_layout)
    branch = _out(repo, "branch", "--show-current")
    _remote_out(remote, "config", "receive.advertisePushOptions", "true")
    log_path = tmp_path / "pushes.log"
    _record_pushes_hook(remote, log_path)
    backend = _commit_and_tag(repo, "extra_tag")

    backend.push(["extra_tag"])

    assert log_path.read_text().splitlines() == [
        "push opts=1",
        f"refs/heads/{branch}",
        "refs/tags/extra_tag",
    ]


class _FakeGit:
    def __init__(self, stderrs):
        self.stderrs = list(stderrs)
        self.calls = []

    def execute(self, cmd):
        self.calls.append(cmd)
        stderr = self.stderrs.pop(0)
        if stderr is not None:
            raise git.exc.GitCommandError(cmd, 1, stderr=stderr)


def _mixin(fake):
    init_stamp_logger()
    m = GitOpsMixin()
    m._be = SimpleNamespace(git=fake)
    m.selected_remote = SimpleNamespace(name="origin")
    return m


def test_ci_skip_retry_only_when_push_options_rejected():
    fake = _FakeGit(["fatal: the receiving end does not support push options", None])

    _mixin(fake)._push_with_ci_skip_fallback(["refs/tags/t"])

    assert len(fake.calls) == 2
    assert "ci.skip" in fake.calls[0] and "ci.skip" not in fake.calls[1]


def test_no_ci_skip_retry_on_non_fast_forward():
    fake = _FakeGit(["! [rejected] main -> main (non-fast-forward)", None])

    with pytest.raises(git.exc.GitCommandError):
        _mixin(fake)._push_with_ci_skip_fallback(["refs/tags/t"])

    assert len(fake.calls) == 1
