#!/usr/bin/env python3
"""Put a detached HEAD on its branch (ensure_on_branch), real names only.

See docs/plans/17-detached-head-and-goto.md §4.
"""

from version_stamp.backends.branch_resolver import LEGACY_TRACKING_PREFIX
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator


def _reason(exc):
    return str(exc).replace("\n", " ").strip()


class GitBranchCheckoutMixin:
    """ensure_on_branch and legacy tracking-branch cleanup. Mixed into GitBackend."""

    @measure_runtime_decorator
    def ensure_on_branch(self, require_tip, use_ci_hint, version_branch=None):
        """Check out the branch a detached HEAD belongs to; True when on one.

        require_tip (commit commands): only a selected-remote branch whose tip
        is HEAD, and only when no local branch contains HEAD (an explicit
        local detach stays detached). Otherwise (goto back) any branch
        containing HEAD, checked out at its tip.
        """
        self._delete_stale_tracking_branches()
        if not self.in_detached_head():
            return True

        hexsha = self._be.head.commit.hexsha
        if require_tip and self._branches_under(hexsha, "refs/heads/"):
            VMN_LOGGER.debug(f"Local branches contain detached HEAD {hexsha}")
            return False

        choice = self.resolve_branch(hexsha, require_tip, use_ci_hint, version_branch)
        if choice is None:
            VMN_LOGGER.debug(f"No branch to check out for detached HEAD {hexsha}")
            return False
        if choice.rule == "legacy":
            self._warn_ambiguous(choice)

        try:
            if require_tip:
                name = self._check_out_at(choice.name, hexsha)
            else:
                name = self._check_out_tip(choice)
        except Exception as exc:
            VMN_LOGGER.error(
                f"Failed to check out branch {choice.name}: {_reason(exc)}"
            )
            VMN_LOGGER.debug("Exception info: ", exc_info=True)
            return False

        self.active_branch = name
        self.remote_active_branch = self.get_remote_tracking_branch(name)
        self.detached_head = self.in_detached_head()
        return not self.detached_head

    def _warn_ambiguous(self, choice):
        VMN_LOGGER.warning(
            f"Detached HEAD belongs to several branches: "
            f"{', '.join(sorted(choice.candidates))}. Using {choice.name} "
            "(the first alphabetically). Set your CI's branch variable "
            "(e.g. BRANCH_NAME) or check out the branch first "
            "(git checkout <branch>) to choose."
        )

    def _check_out_tip(self, choice):
        if self._local_branch_exists(choice.name):
            self._be.git.checkout(choice.name)
        else:
            remote_ref = f"{self.selected_remote.name}/{choice.name}"
            self._be.git.checkout("-b", choice.name, "--track", remote_ref)
        return choice.name

    def _check_out_at(self, name, hexsha):
        """Check out local `name` at hexsha (= its remote's tip), creating or
        fast-forwarding it; the legacy tracking branch if it diverged."""
        remote_ref = f"{self.selected_remote.name}/{name}"
        if not self._local_branch_exists(name):
            self._be.git.checkout("-b", name, "--track", remote_ref)
            return name

        if self._is_ancestor(name, hexsha) and name not in self._checked_out_branches():
            self._be.git.branch("-f", name, hexsha)
            self._be.git.checkout(name)
            if self.get_remote_tracking_branch(name) is None:
                self._be.git.branch(f"--set-upstream-to={remote_ref}", name)
            return name

        legacy = (
            f"{LEGACY_TRACKING_PREFIX}{remote_ref.replace('/', '_')}__from_{hexsha[:5]}"
        )
        VMN_LOGGER.warning(
            f"Local branch {name} has commits that are not on {remote_ref} "
            f"(or is checked out in another worktree); using {legacy} instead. "
            f"Push or delete local {name} to stamp on it."
        )
        self._be.git.checkout("-b", legacy, "--track", remote_ref)
        return legacy

    def _is_ancestor(self, ref, hexsha):
        try:
            self._be.git.merge_base("--is-ancestor", ref, hexsha)
        except Exception:
            return False
        return True

    def _checked_out_branches(self):
        out = self._be.git.worktree("list", "--porcelain")
        prefix = "branch refs/heads/"
        return {
            line[len(prefix) :] for line in out.splitlines() if line.startswith(prefix)
        }

    def _delete_stale_tracking_branches(self):
        """Delete legacy tracking branches with nothing beyond the selected
        remote that no worktree has checked out (their name is vmn's own)."""
        if self.selected_remote is None:
            return
        names = self._be.git.for_each_ref(
            "--format=%(refname:short)", f"refs/heads/{LEGACY_TRACKING_PREFIX}*"
        ).split()
        if not names:
            return
        busy = self._checked_out_branches()
        remotes = f"--remotes={self.selected_remote.name}"
        for name in names:
            if name in busy or self._be.git.rev_list("-n1", name, "--not", remotes):
                continue
            self._be.git.branch("-D", name)
            VMN_LOGGER.debug(f"Deleted stale branch {name}")
