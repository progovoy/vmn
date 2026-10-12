"""``import-mlflow --repo <path>`` (plan 18 §3.6): when a run's source commit
is in a local checkout, its features' ``changed`` are the files and symbols of
``git diff $(git merge-base <default branch> <commit>) <commit>`` — the
branch's cumulative change, marked ``changed_source: commit``. The default
branch is origin/HEAD's target, else ``main``, else ``master``.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from backfill_helpers import host_logs
from mlflow_fixtures import MlflowFixtureBuilder
from vmn_exp.importers import commit_changes
from vmn_exp.importers.commit_changes import CommitChanges, default_branch
from vmn_exp.importers.import_records import import_run, run_verstr
from vmn_exp.importers.mlflow_filestore import iter_runs
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "myapp"
RUN_ID = "c" * 32
TRAIN = "def train():\n    lr = 0.1\n    return lr\n\n\ndef evaluate():\n    return 1\n"


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), check=True,
                          capture_output=True, text=True).stdout.strip()


def _init(path, branch="main"):
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "checkout", "-q", "-b", branch)
    _git(path, "config", "user.email", "t@acme.io")
    _git(path, "config", "user.name", "T")
    return path


def _commit(repo, files, message):
    for name, text in files.items():
        (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    """main: base, then a docs commit after the branch point; feat/focal: two
    commits on train.py plus a new loss.py. Returns (repo, base, tip)."""
    path = _init(tmp_path / "repo")
    base = _commit(path, {"train.py": TRAIN, "README.md": "hi\n"}, "base")
    _git(path, "checkout", "-q", "-b", "feat/focal")
    _commit(path, {"train.py": TRAIN.replace("0.1", "0.01"),
                   "loss.py": "def focal():\n    return 0\n"}, "focal loss")
    tip = _commit(path, {"train.py": TRAIN.replace("0.1", "0.01")
                         .replace("return 1", "return 2")}, "eval tweak")
    _git(path, "checkout", "-q", "main")
    _commit(path, {"README.md": "hello\n"}, "docs")
    return path, base, tip


def _changed(result):
    return {k: set(v) for k, v in result["changed"].items()}


def test_a_branch_commit_changed_what_its_branch_changed_since_the_default(repo):
    path, _, tip = repo

    result = CommitChanges(str(path))(tip)

    assert result["changed_source"] == "commit"
    changed = _changed(result)
    assert changed["files"] == {"train.py", "loss.py"}  # README.md moved on main only
    assert {"train.py::train", "train.py::evaluate"} <= changed["symbols"]


def test_a_commit_already_on_the_default_branch_changed_nothing_of_its_own(repo):
    path, base, _ = repo

    assert CommitChanges(str(path))(base) is None


@pytest.mark.parametrize("commit", ["0" * 40, "", None])
def test_a_commit_the_checkout_lacks_gives_nothing(repo, commit):
    assert CommitChanges(str(repo[0]))(commit) is None


def test_a_path_that_is_no_checkout_gives_nothing(tmp_path, repo):
    assert CommitChanges(str(tmp_path / "nowhere"))(repo[2]) is None


def test_origin_head_names_the_default_branch(tmp_path, repo):
    path, _, tip = repo
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(path), str(clone))
    _git(clone, "checkout", "-q", "--detach")
    _git(clone, "branch", "-f", "main", tip)  # a stale local main is not the default

    assert default_branch(str(clone)) == "refs/remotes/origin/main"
    assert _changed(CommitChanges(str(clone))(tip))["files"] == {"train.py", "loss.py"}


def test_master_is_the_default_without_origin_head_or_main(tmp_path):
    path = _init(tmp_path / "old", branch="master")
    _commit(path, {"a.py": "x = 1\n"}, "base")

    assert default_branch(str(path)) == "master"


def test_a_checkout_without_a_default_branch_gives_nothing(tmp_path):
    path = _init(tmp_path / "dev", branch="dev")
    tip = _commit(path, {"a.py": "x = 1\n"}, "base")

    assert default_branch(str(path)) is None
    assert CommitChanges(str(path))(tip) is None


def test_runs_of_one_commit_diff_it_once(repo, monkeypatch):
    path, _, tip = repo
    diffs = []
    real = commit_changes._git_output

    def counting(cwd, args):
        if args[0] == "diff":
            diffs.append(args)
        return real(cwd, args)

    monkeypatch.setattr(commit_changes, "_git_output", counting)
    changes = CommitChanges(str(path))
    results = []
    threads = [threading.Thread(target=lambda: results.append(changes(tip)))
               for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(diffs) == 1
    assert all(r == results[0] for r in results)


def _mlflow_run(tmp_path, commit):
    mlruns = tmp_path / "mlruns"
    builder = MlflowFixtureBuilder(mlruns)
    builder.add_experiment("1", "exp_one")
    builder.add_run("1", RUN_ID, tags={"mlflow.source.git.commit": commit,
                                       "mlflow.user": "alice"})
    return next(iter_runs(mlruns))


def _features(storage):
    return [e for e in storage.load_merged_log(APP, run_verstr(RUN_ID))
            if e.get("type") == "features"]


def test_an_import_with_a_checkout_records_the_commits_changes(tmp_path, repo):
    path, _, tip = repo
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")

    run = _mlflow_run(tmp_path, tip)
    assert import_run(storage, APP, run, commit_changes=CommitChanges(str(path))) == "created"

    [entry] = _features(storage)
    assert entry["changed_source"] == "commit"
    assert set(entry["changed"]["files"]) == {"train.py", "loss.py"}
    assert entry["author"] == {"os_user": "alice", "source": "mlflow"}


def test_refresh_with_a_checkout_adds_changes_to_features_without_them(
        tmp_path, repo, monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "refresher")
    path, _, tip = repo
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    run = _mlflow_run(tmp_path, tip)
    assert import_run(storage, APP, run) == "created"
    changes = CommitChanges(str(path))

    assert import_run(storage, APP, run, refresh_features=True,
                      commit_changes=changes) == "refreshed"
    assert import_run(storage, APP, run, refresh_features=True,
                      commit_changes=changes) == "skipped"

    by_writer = host_logs(storage, APP, run_verstr(RUN_ID))
    [first] = [e for e in by_writer["mlflow-import"] if e["type"] == "features"]
    [refreshed] = [e for e in by_writer["refresher"] if e["type"] == "features"]
    assert "changed" not in first
    assert refreshed["changed_source"] == "commit"
    assert set(refreshed["changed"]["files"]) == {"train.py", "loss.py"}
