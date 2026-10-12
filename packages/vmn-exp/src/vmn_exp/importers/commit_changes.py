"""What an imported run's source commit changed, read from a local checkout
(``import-mlflow --repo``; plan 18 §3.6).

MLflow keeps no diff, only the commit a run ran at. When the checkout has it,
the run's ``changed`` files and symbols are those of
``git diff $(git merge-base <default branch> <commit>) <commit>``: the branch's
cumulative change rather than the run's own, hence ``changed_source: commit``
(similar runs weigh it half). The default branch is origin/HEAD's target, else
``main``, ``master``, ``origin/main``, ``origin/master`` (a CI checkout may
have no local branch). The diff runs no textconv or external diff driver and
is read up to :data:`MAX_DIFF_BYTES` (``truncated`` past it). A checkout
without the commit or a default branch, or a commit with no change of its
own, gives nothing.
"""
from __future__ import annotations

import subprocess
import threading
from typing import Any

from version_stamp.api import _commit_exists
from vmn_exp.core.features import features_from_patches

_GIT_TIMEOUT_SEC = 120
# The most of git's output read; a branch diff past it counts as truncated.
MAX_DIFF_BYTES = 5 * 1024 * 1024
# (name returned, ref) of the default branch candidates after origin/HEAD.
_DEFAULT_BRANCHES = (
    ("main", "refs/heads/main"),
    ("master", "refs/heads/master"),
    ("refs/remotes/origin/main", "refs/remotes/origin/main"),
    ("refs/remotes/origin/master", "refs/remotes/origin/master"),
)


class _CutOutput(str):
    """git output :func:`_git_output` stopped reading at :data:`MAX_DIFF_BYTES`
    (complete lines only)."""


def _git_output(cwd, args) -> str | None:
    """git *args*' stdout in *cwd* (a :class:`_CutOutput` past
    :data:`MAX_DIFF_BYTES`), or None when git fails."""
    try:
        proc = subprocess.Popen(["git", *args], cwd=cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
    except OSError:
        return None
    timer = threading.Timer(_GIT_TIMEOUT_SEC, proc.kill)
    timer.start()
    try:
        data = proc.stdout.read(MAX_DIFF_BYTES + 1)
        cut = len(data) > MAX_DIFF_BYTES
        if cut:
            proc.kill()
        proc.stdout.close()
        code = proc.wait()
    finally:
        timer.cancel()
    if cut:
        return _CutOutput(_text(data[:data.rfind(b"\n", 0, MAX_DIFF_BYTES) + 1]))
    return _text(data) if code == 0 else None


def _text(data):
    """*data* decoded with newlines translated, as text-mode subprocess output is."""
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def default_branch(repo) -> str | None:
    """The branch a checkout's work merges into: origin/HEAD's target, else
    ``main``, ``master``, ``origin/main``, ``origin/master``; None without any."""
    head = (_git_output(repo, ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"])
            or "").strip()
    if head and _commit_exists(repo, head):
        return head
    for name, ref in _DEFAULT_BRANCHES:
        if _commit_exists(repo, ref):
            return name
    return None


def _changes(repo, branch, commit) -> dict[str, Any] | None:
    base = (_git_output(repo, ["merge-base", branch, commit]) or "").strip()
    if not base:
        return None
    # -U0: each hunk's @@ context names the function its change is in
    diff = _git_output(repo, ["diff", "--no-color", "--no-ext-diff", "--no-textconv",
                              "-U0", base, commit])
    parsed = features_from_patches([diff or ""])
    if not any(parsed["changed"].values()):
        return None
    result = {"changed": parsed["changed"], "changed_source": "commit"}
    if parsed.get("truncated") or isinstance(diff, _CutOutput):
        result["truncated"] = True
    return result


class CommitChanges:
    """``commit -> {"changed", "changed_source": "commit"[, "truncated"]}``
    (or None) in the checkout *repo*. Each commit is diffed once, also when
    the importer's workers ask for it together."""

    def __init__(self, repo):
        self.repo = repo
        self._branch = default_branch(repo)
        self._lock = threading.Lock()
        self._commit_locks: dict[str, threading.Lock] = {}
        self._results: dict[str, dict[str, Any] | None] = {}

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
        if not self._branch or not _commit_exists(self.repo, commit):
            return None
        return _changes(self.repo, self._branch, commit)
