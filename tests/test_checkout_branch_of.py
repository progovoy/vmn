"""checkout_branch_of: the branch vmn reads branch confs for at a checkout,
a detached HEAD resolved the way GitBackend resolves it (plan 17), for
callers outside vmn (the vmn-exp UI) through version_stamp.api."""
import subprocess

from island_helpers import _no_ci_env  # noqa: F401 (autouse fixture)
from version_stamp.backends.factory import checkout_branch_of


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
         "--allow-empty", "-m", "first")
    _git(repo, "branch", "feat/x")
    return repo


def test_an_attached_head_is_its_branch(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "feat/x")
    assert checkout_branch_of(str(repo)) == "feat/x"


def test_a_detached_head_is_the_branch_last_checked_out(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "feat/x")
    _git(repo, "checkout", "-q", "--detach")
    assert checkout_branch_of(str(repo)) == "feat/x"


def test_a_ci_branch_hint_wins_for_a_detached_head(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "feat/x")
    _git(repo, "checkout", "-q", "--detach")
    monkeypatch.setenv("BRANCH_NAME", "main")
    assert checkout_branch_of(str(repo)) == "main"


def test_a_detached_head_on_no_branch_is_none(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "--detach")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
         "--allow-empty", "-m", "loose")
    assert checkout_branch_of(str(repo)) is None


def test_a_directory_that_is_no_git_repo_is_none(tmp_path):
    assert checkout_branch_of(str(tmp_path)) is None
