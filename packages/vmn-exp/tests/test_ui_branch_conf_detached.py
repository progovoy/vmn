"""Plan 22 F3 with a detached HEAD: the UI reads the conf of the branch vmn
resolves a detached checkout to (CI env hint > branch last checked out > ...,
through ``version_stamp.api.checkout_branch_of``), so a CI-style checkout's
branch conf applies; an attached HEAD stays process-free and a detached one
is resolved once per (checkout, HEAD)."""
import os
import subprocess

import pytest
import version_stamp.api as vmn_api
from version_stamp.backends.branch_resolver import CI_BRANCH_ENV_VARS
from vmn_exp.ui.readers import branch_conf

APP = "app"


@pytest.fixture(autouse=True)
def _no_ci_env(monkeypatch):
    for name in (*CI_BRANCH_ENV_VARS, "GITHUB_REF_TYPE"):
        monkeypatch.delenv(name, raising=False)
    branch_conf.detached_branch.cache_clear()


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def _conf(repo, *branch):
    folder = os.path.join(str(repo), ".vmn", APP, *(("branch_conf",) + branch if branch else ()))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "conf.yml")
    open(path, "w").close()
    return os.path.realpath(path)


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "first")
    _git(repo, "branch", "feat/x")
    _conf(repo)
    return repo


def _path(repo):
    return os.path.realpath(branch_conf.app_conf_path(str(repo), APP))


def test_a_detached_head_reads_the_branch_it_was_checked_out_from(repo):
    want = _conf(repo, "feat", "x")
    _git(repo, "checkout", "-q", "feat/x")
    _git(repo, "checkout", "-q", "--detach")
    assert _path(repo) == want


def test_a_ci_branch_hint_picks_the_detached_heads_branch(repo, monkeypatch):
    want = _conf(repo, "main")
    _conf(repo, "feat", "x")
    _git(repo, "checkout", "-q", "feat/x")
    _git(repo, "checkout", "-q", "--detach")
    monkeypatch.setenv("GITHUB_HEAD_REF", "main")
    assert _path(repo) == want


def test_a_detached_head_on_no_branch_reads_the_apps_conf(repo):
    _conf(repo, "feat", "x")
    _git(repo, "checkout", "-q", "--detach")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "loose")
    assert _path(repo) == os.path.realpath(os.path.join(str(repo), ".vmn", APP, "conf.yml"))


def _counting(monkeypatch):
    calls = []
    real = vmn_api.checkout_branch_of

    def counted(root_path):
        calls.append(root_path)
        return real(root_path)

    monkeypatch.setattr(vmn_api, "checkout_branch_of", counted)
    return calls


def test_the_detached_resolution_is_cached_per_head(repo, monkeypatch):
    calls = _counting(monkeypatch)
    _git(repo, "checkout", "-q", "feat/x")
    _git(repo, "checkout", "-q", "--detach")
    for _ in range(3):
        branch_conf.app_conf_path(str(repo), APP)
    assert len(calls) == 1
    _git(repo, "commit", "-q", "--allow-empty", "-m", "next")  # a new HEAD
    branch_conf.app_conf_path(str(repo), APP)
    assert len(calls) == 2


def test_an_attached_head_runs_no_resolution(repo, monkeypatch):
    calls = _counting(monkeypatch)
    want = _conf(repo, "feat", "x")
    _git(repo, "checkout", "-q", "feat/x")
    assert _path(repo) == want
    assert calls == []


def test_a_failing_resolution_reads_the_apps_conf(repo, monkeypatch):
    def broken(root_path):
        raise ValueError("bad checkout")

    monkeypatch.setattr(vmn_api, "checkout_branch_of", broken)
    _conf(repo, "feat", "x")
    _git(repo, "checkout", "-q", "feat/x")
    _git(repo, "checkout", "-q", "--detach")
    assert _path(repo) == os.path.realpath(os.path.join(str(repo), ".vmn", APP, "conf.yml"))
