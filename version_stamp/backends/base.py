#!/usr/bin/env python3
"""Abstract base class for VCS backends.

The static version math methods that were on VMNBackend have moved to
``version_stamp.core.version_math``.  This module retains only the
instance-level interface that concrete backends must implement.
"""
from abc import ABC, abstractmethod

from version_stamp.core.version_math import (  # noqa: F401 — re-export for convenience
    app_name_to_tag_name,
    deserialize_tag_name,
    deserialize_vmn_tag_name,
    deserialize_vmn_version,
    gen_unique_id,
    get_base_vmn_version,
    get_root_app_name_from_name,
    get_utemplate_formatted_version,
    serialize_vmn_base_version,
    serialize_vmn_tag_name,
    serialize_vmn_version,
    tag_name_to_app_name,
)


class VMNBackend(ABC):
    def __init__(self, btype):
        self._type = btype

    def type(self):
        return self._type

    # ── Static helpers re-exported from version_math ─────────────
    # Keep them as static methods on the class so existing callers
    # like ``VMNBackend.serialize_vmn_tag_name(...)`` keep working.

    app_name_to_tag_name = staticmethod(app_name_to_tag_name)
    tag_name_to_app_name = staticmethod(tag_name_to_app_name)
    gen_unique_id = staticmethod(gen_unique_id)
    get_utemplate_formatted_version = staticmethod(get_utemplate_formatted_version)
    get_root_app_name_from_name = staticmethod(get_root_app_name_from_name)
    serialize_vmn_tag_name = staticmethod(serialize_vmn_tag_name)
    serialize_vmn_version = staticmethod(serialize_vmn_version)
    serialize_vmn_base_version = staticmethod(serialize_vmn_base_version)
    get_base_vmn_version = staticmethod(get_base_vmn_version)
    deserialize_tag_name = staticmethod(deserialize_tag_name)
    deserialize_vmn_version = staticmethod(deserialize_vmn_version)
    deserialize_vmn_tag_name = staticmethod(deserialize_vmn_tag_name)

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
        ...
