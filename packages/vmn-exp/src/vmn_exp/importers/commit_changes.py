"""What an imported run's source commit changed, read from a local checkout
(``import-mlflow --repo``; plan 18 §3.6).

MLflow keeps no diff, only the commit a run ran at. When the checkout has it,
the run's ``changed`` files and symbols are those of
``git diff $(git merge-base <default branch> <commit>) <commit>``: the branch's
cumulative change rather than the run's own, hence ``changed_source: commit``
(similar runs weigh it half). The default branch is origin/HEAD's target, else
``main``, else ``master``. A checkout without the commit or a default branch,
or a commit with no change of its own, gives nothing.
"""
from __future__ import annotations

import subprocess
import threading
from typing import Any

from version_stamp.api import _commit_exists
from vmn_exp.core.features import features_from_patches

_GIT_TIMEOUT_SEC = 120
_UNSET = object()


def _git_output(cwd, args) -> str | None:
    """git *args*' stdout in *cwd*, or None when git fails."""
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              encoding="utf-8", errors="replace",
                              timeout=_GIT_TIMEOUT_SEC)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def default_branch(repo) -> str | None:
    """The branch a checkout's work merges into: origin/HEAD's target, else
    ``main``, else ``master``; None without any."""
    head = (_git_output(repo, ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"])
            or "").strip()
    if head:
        return head
    for name in ("main", "master"):
        if _git_output(repo, ["rev-parse", "--verify", "--quiet",
                              f"refs/heads/{name}^{{commit}}"]) is not None:
            return name
    return None


def _changes(repo, branch, commit) -> dict[str, Any] | None:
    base = (_git_output(repo, ["merge-base", branch, commit]) or "").strip()
    if not base:
        return None
    # -U0: each hunk's @@ context names the function its change is in
    diff = _git_output(repo, ["diff", "--no-color", "--no-ext-diff", "-U0", base, commit])
    parsed = features_from_patches([diff or ""])
    if not any(parsed["changed"].values()):
        return None
    result = {"changed": parsed["changed"], "changed_source": "commit"}
    if parsed.get("truncated"):
        result["truncated"] = True
    return result


class CommitChanges:
    """``commit -> {"changed", "changed_source": "commit"[, "truncated"]}``
    (or None) in the checkout *repo*. Each commit is diffed once, also when
    the importer's workers ask for it together."""

    def __init__(self, repo):
        self.repo = repo
        self._lock = threading.Lock()
        self._commit_locks: dict[str, threading.Lock] = {}
        self._results: dict[str, dict[str, Any] | None] = {}
        self._branch: Any = _UNSET

    def __call__(self, commit) -> dict[str, Any] | None:
        if not commit:
            return None
        with self._lock:
            commit_lock = self._commit_locks.setdefault(commit, threading.Lock())
        with commit_lock:
            if commit not in self._results:
                self._results[commit] = self._compute(commit)
            return self._results[commit]

    def _compute(self, commit):
        if not _commit_exists(self.repo, commit):
            return None
        branch = self._default_branch()
        return _changes(self.repo, branch, commit) if branch else None

    def _default_branch(self):
        with self._lock:
            if self._branch is _UNSET:
                self._branch = default_branch(self.repo)
            return self._branch
