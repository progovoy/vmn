"""How many git processes `vmn-exp run` and SDK `start_run` spawn on an
initialised app, so the wrapper's cost cannot grow unnoticed (plan 39 B9a).
Bounds are the measured counts plus a small margin; a failure prints
git_budget.summarize. Measured in-process, outside a supervisor, so plan 38
A5's adoption does not change what these count; the adopted case grants the
offer by hand (plan 39 B9d)."""
import os

import git
import pytest
from exp_helpers import _bootstrap, _exp
from git_budget import summarize

from version_stamp.core import git_cmd
from vmn_exp.sdk import start_run

# Measured at 286c7b4e: 16 git processes for each case (a second start_run too).
# B9d: the backend asks for its remote URL once (3 -> 1), so 14; an adopted
# start_run builds a stamper only to find the store and its conf: 6.
MARGIN = 1
RUN_NOOP_BUDGET = 14 + MARGIN
START_RUN_BUDGET = 14 + MARGIN
ADOPTED_START_RUN_BUDGET = 6 + MARGIN


@pytest.fixture(autouse=True)
def _clean_experiment_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_EXP_ADOPT_RUN_ID",
                "VMN_EXP_ADOPT_PID"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def git_calls(monkeypatch):
    """Every git command vmn runs (GitPython and core.git_cmd), as argv lists.
    Copied from tests/test_git_process_budget.py."""
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


def _start_run_counted(app_layout, git_calls):
    git_calls.clear()
    with start_run(app_layout.app_name):
        pass
    return list(git_calls)


def test_run_of_a_noop_command_costs_at_most_N_git_processes(app_layout, git_calls):
    _bootstrap(app_layout)
    git_calls.clear()

    assert _exp(app_layout.app_name, action="run", run_cmd=["true"]) == 0

    assert len(git_calls) <= RUN_NOOP_BUDGET, summarize(git_calls)


def test_sdk_start_run_costs_at_most_N_git_processes(app_layout, git_calls):
    _bootstrap(app_layout)

    calls = _start_run_counted(app_layout, git_calls)

    assert len(calls) <= START_RUN_BUDGET, summarize(calls)


def test_a_second_start_run_costs_no_more_than_the_first(app_layout, git_calls):
    _bootstrap(app_layout)
    first = _start_run_counted(app_layout, git_calls)

    second = _start_run_counted(app_layout, git_calls)

    assert len(second) <= len(first), summarize(second)


def test_an_adopted_start_run_costs_at_most_N_git_processes(app_layout, git_calls,
                                                            monkeypatch):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as offered:
        pass
    monkeypatch.setenv("VMN_EXP_ADOPT_RUN_ID", offered.id)
    monkeypatch.setenv("VMN_EXP_ADOPT_PID", str(os.getppid()))

    calls = _start_run_counted(app_layout, git_calls)

    assert "VMN_EXP_ADOPT_RUN_ID" not in os.environ  # the offer was taken
    assert len(calls) <= ADOPTED_START_RUN_BUDGET, summarize(calls)
