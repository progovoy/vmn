"""git_budget.summarize: what a git-process budget failure prints (plan 39 B9a)."""
from git_budget import summarize

_CALLS = [
    ["git", "rev-parse", "HEAD"],
    ["git", "-C", "/repo", "status", "--porcelain"],
    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    ["git", "-c", "core.quotepath=off", "rev-parse", "--show-toplevel"],
]


def test_summary_counts_calls_per_git_subcommand():
    lines = summarize(_CALLS).splitlines()

    assert "3 rev-parse" in lines
    assert "1 status" in lines


def test_summary_lists_the_most_frequent_subcommand_first():
    lines = summarize(_CALLS).splitlines()

    assert lines[:2] == ["3 rev-parse", "1 status"]
    assert lines[2:] == [" ".join(argv) for argv in _CALLS]


def test_summary_of_no_calls_is_empty():
    assert summarize([]) == ""
