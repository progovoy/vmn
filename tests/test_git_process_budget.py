"""How many git processes a stamp/goto runs, so detached paths don't regress
(plan 17 F11). Bounds were set from measurements with a small margin."""
import git
import pytest

from helpers import _goto, _stamp_app
from island_helpers import (  # noqa: F401 (_no_ci_env is an autouse fixture)
    _ci_checkout,
    _no_ci_env,
    _stamped_repo,
)
from version_stamp.core import git_cmd

# Measured: attached stamp vs the same stamp from a CI-style detached checkout.
DETACHED_STAMP_EXTRA = 2


@pytest.fixture
def git_calls(monkeypatch):
    """Every git command vmn runs (GitPython and core.git_cmd), as argv lists."""
    calls = []
    original_execute = git.cmd.Git.execute
    original_run_git = git_cmd.subprocess.run

    def execute(self, command, *args, **kwargs):
        calls.append([str(part) for part in command])
        return original_execute(self, command, *args, **kwargs)

    def run(argv, *args, **kwargs):
        if argv and argv[0] == "git":
            calls.append([str(part) for part in argv])
        return original_run_git(argv, *args, **kwargs)

    monkeypatch.setattr(git.cmd.Git, "execute", execute)
    monkeypatch.setattr(git_cmd.subprocess, "run", run)
    return calls


def _containment_lookups(calls):
    return [c for c in calls if "for-each-ref" in c and "--contains" in c]


def _stamp_counted(app_layout, git_calls):
    git_calls.clear()
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    return len(git_calls)


def _next_commit(app_layout):
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg")


def test_detached_ci_stamp_costs_at_most_a_few_git_processes(app_layout, git_calls):
    repo, default, _ = _stamped_repo(app_layout)
    _next_commit(app_layout)
    attached = _stamp_counted(app_layout, git_calls)
    _next_commit(app_layout)
    _ci_checkout(repo, default)

    detached = _stamp_counted(app_layout, git_calls)

    assert detached <= attached + DETACHED_STAMP_EXTRA, (attached, detached)
    assert len(_containment_lookups(git_calls)) == 1


def test_goto_back_runs_one_containment_lookup_per_commit(app_layout, git_calls):
    _stamped_repo(app_layout)
    _next_commit(app_layout)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    assert _goto(app_layout.app_name, version="0.0.1") == 0

    git_calls.clear()
    assert _goto(app_layout.app_name) == 0

    lookups = [tuple(c) for c in _containment_lookups(git_calls)]
    assert len(lookups) == len(set(lookups)), lookups
