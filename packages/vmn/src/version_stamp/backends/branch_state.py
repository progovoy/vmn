#!/usr/bin/env python3
"""The active branch of a GitBackend, resolved on first use.

Resolving costs git processes (upstream lookup; for a detached HEAD the
branches containing it and the reflog), and many backends never need it — a
dep that is only checked for a detached HEAD, a goto checkout. The state is the
one the eager constructor computed: it is resolved for the HEAD the backend was
built at, and materialized before any change that could alter that answer
(leaving a branch, moving refs). Assignments override it, as they did before.

local_branch is the git ref name (the checked-out branch, or the branch a
detached HEAD resolved to); active_branch is the branch identity used for
branch confs, policies and stamped_on_branch: the same name, except that a
legacy vmn_tracking_remote__* branch counts as its upstream.
"""
from version_stamp.backends.branch_resolver import _strip_prefixes
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.utils import is_legacy_tracking_branch

_FIELDS = ("local_branch", "remote_active_branch", "active_branch_is_local")


def _branch_field(name):
    def get(self):
        return self._loaded_branch_state()[name]

    def set_(self, value):
        self._loaded_branch_state()[name] = value

    return property(get, set_)


class GitBranchStateMixin:
    """Lazy active-branch state. Mixed into GitBackend."""

    local_branch = _branch_field("local_branch")
    remote_active_branch = _branch_field("remote_active_branch")
    # Whether local_branch names a local branch (else only its remote has it).
    active_branch_is_local = _branch_field("active_branch_is_local")

    @property
    def active_branch(self):
        name = self.local_branch
        if is_legacy_tracking_branch(name) and self.remote_active_branch:
            return _strip_prefixes(self.remote_active_branch, self._remote_name())
        return name

    @active_branch.setter
    def active_branch(self, name):
        self.local_branch = name

    def _init_branch_state(self):
        self._branch_state = None
        # (hexsha, refs) of the containment lookup a lazy load just ran.
        self._resolution_refs = None
        self._head_at_init = self._current_head()

    def _current_head(self):
        """(detached, branch name or hexsha) of HEAD; reads files only."""
        if self.in_detached_head():
            return True, self._be.head.commit.hexsha
        return False, self._be.active_branch.name

    def _loaded_branch_state(self):
        if self._branch_state is None:
            name, remote, refs = self._resolve_active_branch(self._head_at_init)
            self._resolution_refs = refs
            is_local = name is not None and remote is None
            if is_local:
                remote = self.get_remote_tracking_branch(name)
            self._branch_state = dict(zip(_FIELDS, (name, remote, is_local)))
        return self._branch_state

    def _resolve_active_branch(self, head=None):
        """(name, remote, refs) of the active branch for head (default: HEAD
        now). remote is the selected-remote branch when a detached HEAD
        resolved to one with no local branch, else None (the caller looks the
        upstream up); refs is (hexsha, containment lookup) when one ran."""
        detached, ref = head or self._current_head()
        if not detached:
            return ref, None, None

        refs = (ref, self._refs_containing(ref))
        choice = self.resolve_branch(ref, refs=refs[1])
        if choice is None:
            return None, None, refs
        if choice.rule == "legacy":
            VMN_LOGGER.debug(
                f"Detached HEAD is on several branches {choice.candidates}; "
                f"reporting {choice.name}"
            )
        if choice.is_local:
            return choice.name, None, refs
        return choice.name, f"{self.selected_remote.name}/{choice.name}", refs

    def _before_ref_change(self):
        """Fix the branch state before refs move under it (fetch, push,
        branch create/delete, upstream changes)."""
        self._loaded_branch_state()
        self._resolution_refs = None

    def _before_head_move(self):
        """_head_at_init pins the answer across HEAD moves, except that leaving
        a branch adds a reflog entry ("moving from <branch>") a detached HEAD's
        resolution reads: resolve first in that case."""
        if self._head_at_init[0] and not self.in_detached_head():
            self._loaded_branch_state()

    def _refs_for(self, hexsha):
        """The containment lookup the lazy load ran for hexsha (no ref has
        changed since), else a new one."""
        if self._resolution_refs and self._resolution_refs[0] == hexsha:
            return self._resolution_refs[1]
        return self._refs_containing(hexsha)
