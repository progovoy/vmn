#!/usr/bin/env python3
"""Abstract base class for VCS backends.

The static version math methods that were on VMNBackend have moved to
``version_stamp.core.version_math``.  This module retains only the
instance-level interface that concrete backends must implement.
"""
from abc import ABC, abstractmethod


class VMNBackend(ABC):
    def __init__(self, btype):
        self._type = btype

    def type(self):
        return self._type

    # ── Abstract interface ───────────────────────────────────────

    @abstractmethod
    def prepare_for_remote_operation(self):
        ...

    @abstractmethod
    def get_active_branch(self):
        ...

    @abstractmethod
    def remote(self):
        ...

    @abstractmethod
    def get_last_user_changeset(self, version_files_to_track_diff, name):
        ...

    @abstractmethod
    def get_actual_deps_state(self, vmn_root_path, paths):
        ...

    @abstractmethod
    def perform_cached_fetch(self, force=False):
        ...

    @abstractmethod
    def get_latest_stamp_tags(self, app_name, root_context, type=None):
        ...

    @abstractmethod
    def get_tag_version_info(self, tag_name):
        """``(tag_name, ver_infos)``; ``ver_infos`` is always a dict ({} if none)."""
