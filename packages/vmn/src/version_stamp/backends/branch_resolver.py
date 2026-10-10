#!/usr/bin/env python3
"""Which branch a detached HEAD belongs to, and putting HEAD on it.

Resolving never changes the repo. Only ensure_on_branch() checks a branch
out, and only callers that need one (commit commands, goto back) call it.
See docs/plans/17-detached-head-and-goto.md.
"""

import os
from collections import namedtuple

from version_stamp.core.logging import measure_runtime_decorator

LEGACY_TRACKING_PREFIX = "vmn_tracking_remote__"

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
            return name[len(prefix) :]
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
        """({local branch: sha}, {selected-remote branch: sha}) containing hexsha."""
        prefixes = ["refs/heads/"]
        remote_prefix = None
        if self.selected_remote is not None:
            remote_prefix = f"refs/remotes/{self.selected_remote.name}/"
            prefixes.append(remote_prefix)
        out = self._be.git.for_each_ref(
            "--contains", hexsha, "--format=%(refname) %(objectname)", *prefixes
        )
        local, remote = {}, {}
        for line in out.splitlines():
            ref, sha = line.rsplit(" ", 1)
            if ref.startswith("refs/heads/"):
                local[ref[len("refs/heads/") :]] = sha
            elif remote_prefix and ref.startswith(remote_prefix):
                name = ref[len(remote_prefix) :]
                if name != "HEAD":
                    remote[name] = sha
        return local, remote

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
        self, hexsha, require_tip=False, use_ci_hint=False, version_branch=None
    ):
        """The BranchChoice for hexsha, or None when no branch qualifies.

        A branch qualifies when it contains hexsha; with require_tip only
        selected-remote branches whose tip is hexsha do. No side effects.
        """
        local, remote = self._refs_containing(hexsha)
        if require_tip:
            candidates = [b for b, sha in remote.items() if sha == hexsha]
        else:
            candidates = list(dict.fromkeys([*local, *remote]))
        if not candidates:
            return None

        tips = [b for b in candidates if hexsha in (local.get(b), remote.get(b))]
        remote_name = self._remote_name()
        version = (
            _strip_prefixes(version_branch, remote_name) if version_branch else None
        )
        rules = (
            ("ci", lambda: ci_branch_hints(remote_name) if use_ci_hint else ()),
            ("reflog", lambda: (self._last_checked_out_branch(),)),
            ("tip", lambda: tips if len(tips) == 1 else ()),
            ("version", lambda: (version,)),
            ("unique", lambda: candidates if len(candidates) == 1 else ()),
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
        if (
            name
            and name.startswith(LEGACY_TRACKING_PREFIX)
            and self.remote_active_branch
        ):
            return _strip_prefixes(self.remote_active_branch, self._remote_name())
        return name

    def branch_ref(self):
        """The ref of the active branch: local if it exists, else its remote."""
        if self.active_branch and self._local_branch_exists(self.active_branch):
            return f"refs/heads/{self.active_branch}"
        if self.remote_active_branch:
            return f"refs/remotes/{self.remote_active_branch}"
        return "HEAD"
