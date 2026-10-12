#!/usr/bin/env python3
"""Put a detached HEAD on its branch (ensure_on_branch), real names only.

See docs/plans/17-detached-head-and-goto.md §4.
"""
import functools

from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.utils import (
    is_legacy_tracking_branch,
    legacy_tracking_branch_name,
    one_line_reason,
)


class GitBranchCheckoutMixin:
    """ensure_on_branch and legacy tracking-branch cleanup. Mixed into GitBackend."""

    @measure_runtime_decorator
    def ensure_on_branch(self, require_tip, use_ci_hint=None, version_branch=None):
        """Check out the branch a detached HEAD belongs to; True when on one.

        require_tip (commit commands): only a selected-remote branch whose tip
        is HEAD, and only when no local branch contains HEAD (an explicit
        local detach stays detached). Otherwise (goto back) any branch
        containing HEAD, checked out at its tip. use_ci_hint defaults to the
        backend's.
        """
        # A detached HEAD keeps the branch state it had before anything moves
        # (as when the constructor resolved it); its lookup is reused unless a
        # ref changed since.
        if self.in_detached_head():
            self._loaded_branch_state()
        checked_out = functools.lru_cache(maxsize=None)(self._checked_out_branches)
        self._delete_stale_tracking_branches(checked_out)
        if not self.in_detached_head():
            return True

        hexsha = self._be.head.commit.hexsha
        refs = self._refs_for(hexsha)
        if require_tip and refs[0]:
            VMN_LOGGER.debug(f"Local branches contain detached HEAD {hexsha}")
            return False

        choice = self.resolve_branch(
            hexsha, require_tip, use_ci_hint, version_branch, refs
        )
        if choice is None:
            VMN_LOGGER.debug(f"No branch to check out for detached HEAD {hexsha}")
            return False
        if choice.rule == "legacy":
            self._warn_ambiguous(choice)

        try:
            if require_tip:
                name, upstream = self._check_out_at(choice.name, hexsha, checked_out)
            else:
                name, upstream = self._check_out_tip(choice)
        except Exception as exc:
            VMN_LOGGER.error(
                f"Failed to check out branch {choice.name}: {one_line_reason(exc)}"
            )
            VMN_LOGGER.debug("Exception info: ", exc_info=True)
            return False

        self.local_branch = name
        self.active_branch_is_local = True
        self.remote_active_branch = upstream
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

    def _remote_ref(self, name):
        return f"{self.selected_remote.name}/{name}"

    def _track_remote(self, local_name, remote_ref):
        """Create and check out local_name tracking remote_ref; its upstream."""
        self._be.git.checkout("-b", local_name, "--track", remote_ref)
        return remote_ref

    def _check_out_existing(self, name):
        self.checkout(branch=name)
        return self.get_remote_tracking_branch(name)

    def _check_out_tip(self, choice):
        """(name, upstream) after checking out choice.name as it is locally,
        else created at its remote's tip."""
        if self._local_branch_exists(choice.name):
            return choice.name, self._check_out_existing(choice.name)
        return choice.name, self._track_remote(choice.name, self._remote_ref(choice.name))

    def _check_out_at(self, name, hexsha, checked_out):
        """(name, upstream) after checking out local `name` at hexsha (= its
        remote's tip), creating or fast-forwarding it; the legacy tracking
        branch if it diverged or another worktree has it."""
        remote_ref = self._remote_ref(name)
        if not self._local_branch_exists(name):
            return name, self._track_remote(name, remote_ref)

        if self._is_ancestor(name, hexsha) and name not in checked_out():
            self._be.git.branch("-f", name, hexsha)
            upstream = self._check_out_existing(name)
            if upstream is None:
                self._be.git.branch(f"--set-upstream-to={remote_ref}", name)
                upstream = remote_ref
            return name, upstream

        legacy = legacy_tracking_branch_name(remote_ref, hexsha)
        VMN_LOGGER.warning(
            f"Local branch {name} has commits that are not on {remote_ref} "
            f"(or is checked out in another worktree); using {legacy} instead. "
            f"Push or delete local {name} to stamp on it."
        )
        return legacy, self._track_remote(legacy, remote_ref)

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

    def _delete_stale_tracking_branches(self, checked_out):
        """Delete legacy tracking branches with nothing beyond the selected
        remote that no worktree has checked out (their name is vmn's own)."""
        if self.selected_remote is None:
            return
        names = [h.name for h in self._be.heads if is_legacy_tracking_branch(h.name)]
        if not names:
            return
        remotes = f"--remotes={self.selected_remote.name}"
        for name in names:
            if name in checked_out() or self._be.git.rev_list(
                "-n1", name, "--not", remotes
            ):
                continue
            self._before_ref_change()
            self._be.git.branch("-D", name)
            VMN_LOGGER.debug(f"Deleted stale branch {name}")
