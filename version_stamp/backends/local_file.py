#!/usr/bin/env python3
import glob
import os

import yaml

from version_stamp.backends.base import VMNBackend
from version_stamp.core.constants import (
    RELATIVE_TO_GLOBAL_TYPE,
    VMN_BE_TYPE_LOCAL_FILE,
)
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator


class LocalFileBackend(VMNBackend):
    def __init__(self, repo_path):
        VMNBackend.__init__(self, VMN_BE_TYPE_LOCAL_FILE)

        vmn_dir_path = os.path.join(repo_path, ".vmn")
        if not os.path.isdir(vmn_dir_path):
            raise RuntimeError(
                "LocalFile backend needs to be initialized with a local"
                " path containing .vmn dir in it"
            )

        self.repo_path = repo_path
        self.active_branch = "none"
        self.remote_active_branch = "remote/none"

    @staticmethod
    def _find_snapshot_files(base_dir):
        """Find metadata.yml files in snapshot directories."""
        pattern = os.path.join(base_dir, "*", "metadata.yml")
        return glob.glob(pattern)

    @staticmethod
    def _find_verinfo_files(base_dir):
        """Find .yml files in verinfo directories (backward compat)."""
        return glob.glob(os.path.join(base_dir, "*.yml"))

    def perform_cached_fetch(self, force=False):
        return

    def prepare_for_remote_operation(self):
        return 0

    def get_active_branch(self):
        return "none"

    def remote(self):
        return "none"

    def get_last_user_changeset(self, version_files_to_track_diff, name):
        return "none"

    def _resolve_latest_file(self, app_name, root=False):
        """Find the latest version file, checking snapshots/ first, then verinfo/."""
        if root:
            snap_dir = os.path.join(self.repo_path, ".vmn", app_name, "root_snapshots")
            verinfo_dir = os.path.join(self.repo_path, ".vmn", app_name, "root_verinfo")
        else:
            snap_dir = os.path.join(self.repo_path, ".vmn", app_name, "snapshots")
            verinfo_dir = os.path.join(self.repo_path, ".vmn", app_name, "verinfo")

        # Check snapshots first
        snap_files = self._find_snapshot_files(snap_dir)
        if snap_files:
            return max(snap_files, key=os.path.getmtime)

        # Fall back to verinfo
        verinfo_files = self._find_verinfo_files(verinfo_dir)
        if verinfo_files:
            return max(verinfo_files, key=os.path.getmtime)

        return None

    def _resolve_version_file(self, app_name, verstr, root=False, root_version=None):
        """Find a specific version file, checking snapshots/ first, then verinfo/."""
        if root:
            snap_path = os.path.join(
                self.repo_path, ".vmn", app_name, "root_snapshots",
                str(root_version), "metadata.yml",
            )
            verinfo_path = os.path.join(
                self.repo_path, ".vmn", app_name, "root_verinfo",
                f"{root_version}.yml",
            )
        else:
            snap_path = os.path.join(
                self.repo_path, ".vmn", app_name, "snapshots",
                verstr, "metadata.yml",
            )
            verinfo_path = os.path.join(
                self.repo_path, ".vmn", app_name, "verinfo",
                f"{verstr}.yml",
            )

        if os.path.isfile(snap_path):
            return snap_path
        if os.path.isfile(verinfo_path):
            return verinfo_path
        return None

    def _list_all_version_files(self, app_name, root=False):
        """List all version files from both snapshots/ and verinfo/."""
        if root:
            snap_dir = os.path.join(self.repo_path, ".vmn", app_name, "root_snapshots")
            verinfo_dir = os.path.join(self.repo_path, ".vmn", app_name, "root_verinfo")
        else:
            snap_dir = os.path.join(self.repo_path, ".vmn", app_name, "snapshots")
            verinfo_dir = os.path.join(self.repo_path, ".vmn", app_name, "verinfo")

        files = self._find_snapshot_files(snap_dir) + self._find_verinfo_files(verinfo_dir)
        return files

    def get_first_reachable_version_info(
        self, app_name, root=False, type=RELATIVE_TO_GLOBAL_TYPE
    ):
        ver_infos = {
            "none": {
                "tag_object": None,
                "commit_obj": None,
                "ver_info": None,
            }
        }

        latest_file = self._resolve_latest_file(app_name, root=root)
        if not latest_file:
            return None, {}

        with open(latest_file, "r") as f:
            ver_infos["none"]["ver_info"] = yaml.safe_load(f)
            return "none", ver_infos

    def get_latest_available_tag(self, tag_prefix_filter):
        return None

    def get_actual_deps_state(self, vmn_root_path, paths):
        actual_deps_state = {
            ".": {
                "hash": "0xdeadbeef",
                "remote": "none",
                "vcs_type": VMN_BE_TYPE_LOCAL_FILE,
            }
        }

        return actual_deps_state

    def get_tag_version_info(self, tag_name):
        tagd = VMNBackend.deserialize_vmn_tag_name(tag_name)
        is_root = "root" in tagd.types

        path = self._resolve_version_file(
            tagd.app_name, tagd.verstr, root=is_root,
            root_version=tagd.root_version,
        )

        ver_infos = {}
        if path is not None:
            try:
                with open(path, "r") as f:
                    ver_infos = {
                        tag_name: {
                            "ver_info": None,
                            "tag_object": None,
                            "commit_object": None,
                        }
                    }
                    ver_infos[tag_name]["ver_info"] = yaml.safe_load(f)
            except Exception:
                VMN_LOGGER.debug("Logged Exception message:", exc_info=True)

        return tag_name, ver_infos

    @measure_runtime_decorator
    def get_latest_stamp_tags(
        self, app_name, root_context, type=RELATIVE_TO_GLOBAL_TYPE
    ):
        files = self._list_all_version_files(app_name, root=root_context)

        # sort by modification date
        files.sort(key=os.path.getmtime, reverse=True)

        ver_infos = {}
        tag_names = []
        if files:
            with open(files[0], "r") as f:
                data = yaml.safe_load(f)
                if root_context:
                    ver = data["stamping"]["root_app"]["version"]
                else:
                    ver = data["stamping"]["app"]["_version"]

                tag_name = VMNBackend.serialize_vmn_tag_name(app_name, ver)
                tag_names.append(tag_name)
                ver_infos = {
                    tag_name: {
                        "ver_info": None,
                        "tag_object": None,
                        "commit_object": None,
                    }
                }
                ver_infos[tag_name]["ver_info"] = data

        return tag_names, None, ver_infos
