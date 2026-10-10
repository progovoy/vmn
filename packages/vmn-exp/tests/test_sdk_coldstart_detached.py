"""An SDK cold start in a CI-style detached checkout commits on the real branch."""
import subprocess

import pytest

from vmn_exp.sdk import start_run


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "BRANCH_NAME", "GIT_BRANCH"):
        monkeypatch.delenv(key, raising=False)


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_cold_start_at_the_remote_tip_commits_on_the_real_branch(app_layout):
    repo = app_layout.repo_path
    default = _git(repo, "branch", "--show-current")
    _git(repo, "checkout", "-q", "-f", _git(repo, "rev-parse", "HEAD"))
    _git(repo, "branch", "-q", "-D", default)

    with start_run(app_layout.app_name):
        pass

    assert _git(repo, "branch", "--show-current") == default
    branches = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    assert branches.split() == [default]
    assert f"{app_layout.app_name}_0.0.0" in _git(repo, "tag", "--points-at", "HEAD")
