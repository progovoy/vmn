#!/usr/bin/env python3
"""Which branch a detached HEAD belongs to, and putting HEAD on it.

Resolving never changes the repo. Only ensure_on_branch() checks a branch
out, and only callers that need one (commit commands, goto back) call it.
See docs/plans/17-detached-head-and-goto.md.
"""

import os
from collections import namedtuple

from version_stamp.backends.git_ops import _strip_prefix
from version_stamp.core.constants import LEGACY_TRACKING_PREFIX  # noqa: F401
from version_stamp.core.logging import measure_runtime_decorator
from version_stamp.core.utils import is_legacy_tracking_branch

# The branch a CI job builds, in lookup order (main repo only).
CI_BRANCH_ENV_VARS = (
    "GITHUB_HEAD_REF",
    "GITHUB_REF_NAME",
    "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME",
    "CI_COMMIT_REF_NAME",
    "BRANCH_NAME",
    "GIT_BRANCH",
    "BUILDKITE_BRANCH",
    "CIRCLE_BRANCH",
    "BITBUCKET_BRANCH",
)

# rule: ci | reflog | tip | version | unique | legacy (ambiguous, alphabetical)
BranchChoice = namedtuple("BranchChoice", "name candidates rule is_local")

_CHECKOUT_PREFIX = "checkout: moving from "


def _strip_prefixes(name, remote_name):
    prefixes = ["refs/heads/"]
    if remote_name:
        prefixes += [f"refs/remotes/{remote_name}/", f"{remote_name}/"]
    for prefix in prefixes:
        if name.startswith(prefix):
            return _strip_prefix(name, prefix)
    return name


def ci_branch_hints(remote_name):
    for var in CI_BRANCH_ENV_VARS:
        value = os.environ.get(var, "").strip()
        if not value:
            continue
        if var == "GITHUB_REF_NAME" and os.environ.get("GITHUB_REF_TYPE") != "branch":
            continue
        yield _strip_prefixes(value, remote_name)


class GitBranchResolverMixin:
    """Detached-HEAD branch resolution. Mixed into GitBackend."""

    def _remote_name(self):
        return self.selected_remote.name if self.selected_remote is not None else None

    def _local_branch_exists(self, name):
        return any(head.name == name for head in self._be.heads)

    def _refs_containing(self, hexsha):
        """({local branch: sha}, {selected-remote branch: sha}) containing
        hexsha, in ref order (one for-each-ref)."""
        prefixes = {"refs/heads/": {}}
        remote_name = self._remote_name()
        if remote_name is not None:
            prefixes[f"refs/remotes/{remote_name}/"] = {}
        out = self._be.git.for_each_ref(
            "--contains", hexsha, "--format=%(refname) %(objectname)", *prefixes
        )
        for line in out.splitlines():
            ref, sha = line.rsplit(" ", 1)
            for prefix, names in prefixes.items():
                name = ref[len(prefix) :] if ref.startswith(prefix) else None
                if name and name != "HEAD":
                    names[name] = sha
        local, *remote = prefixes.values()
        return local, (remote[0] if remote else {})

    def _last_checked_out_branch(self):
        """The newest existing local branch HEAD was checked out away from."""
        try:
            out = self._be.git.log("-g", "--format=%gs", "-n", "200", "HEAD")
        except Exception:
            return None
        local_names = {head.name for head in self._be.heads}
        for subject in out.splitlines():
            if not subject.startswith(_CHECKOUT_PREFIX):
                continue
            name = subject[len(_CHECKOUT_PREFIX) :].rsplit(" to ", 1)[0]
            if name in local_names:
                return name
        return None

    @measure_runtime_decorator
    def resolve_branch(
        self,
        hexsha,
        require_tip=False,
        use_ci_hint=None,
        version_branch=None,
        refs=None,
    ):
        """The BranchChoice for hexsha, or None when no branch qualifies.

        A branch qualifies when it contains hexsha; with require_tip only
        selected-remote branches whose tip is hexsha do. use_ci_hint defaults
        to the backend's; version_branch may be a callable, called only when
        that rule is reached; refs is a _refs_containing(hexsha) result the
        caller already has. No side effects.
        """
        local, remote = refs or self._refs_containing(hexsha)
        if require_tip:
            candidates = [b for b, sha in remote.items() if sha == hexsha]
        else:
            candidates = list(dict.fromkeys([*local, *remote]))
        if not candidates:
            return None
        if len(candidates) == 1:
            return BranchChoice(candidates[0], candidates, "unique", candidates[0] in local)

        if use_ci_hint is None:
            use_ci_hint = self.use_ci_hint
        tips = [b for b in candidates if hexsha in (local.get(b), remote.get(b))]
        remote_name = self._remote_name()

        def version():
            name = version_branch() if callable(version_branch) else version_branch
            return (_strip_prefixes(name, remote_name) if name else None,)

        rules = (
            ("ci", lambda: ci_branch_hints(remote_name) if use_ci_hint else ()),
            ("reflog", lambda: (self._last_checked_out_branch(),)),
            ("tip", lambda: tips if len(tips) == 1 else ()),
            ("version", version),
        )
        for rule, names in rules:
            for name in names():
                if name in candidates:
                    return BranchChoice(name, candidates, rule, name in local)

        # Today's pick: first local branch alphabetically, else first remote.
        name = min([b for b in candidates if b in local] or candidates)
        return BranchChoice(name, candidates, "legacy", name in local)

    def logical_branch(self):
        """The branch name to use as an identity (branch confs, policies,
        stamped_on_branch): a legacy tracking branch counts as its upstream."""
        name = self.active_branch
        if is_legacy_tracking_branch(name) and self.remote_active_branch:
            return _strip_prefixes(self.remote_active_branch, self._remote_name())
        return name

    def branch_ref(self):
        """The ref of the active branch: local if it exists, else its remote."""
        if self.active_branch and self.active_branch_is_local:
            return f"refs/heads/{self.active_branch}"
        if self.remote_active_branch:
            return f"refs/remotes/{self.remote_active_branch}"
        return "HEAD"
