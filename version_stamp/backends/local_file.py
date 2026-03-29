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

    def __del__(self):
        pass

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
        if root:
            dir_path = os.path.join(self.repo_path, ".vmn", app_name, "root_verinfo")
            list_of_files = glob.glob(os.path.join(dir_path, "*.yml"))
            if not list_of_files:
                return None, {}

            latest_file = max(list_of_files, key=os.path.getctime)
            with open(latest_file, "r") as f:
                ver_infos["none"]["ver_info"] = yaml.safe_load(f)
                return "none", ver_infos

        dir_path = os.path.join(self.repo_path, ".vmn", app_name, "verinfo")
        list_of_files = glob.glob(os.path.join(dir_path, "*.yml"))
        if not list_of_files:
            return None, {}

        latest_file = max(list_of_files, key=os.path.getctime)

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
        if "root" in tagd.types:
            dir_path = os.path.join(
                self.repo_path, ".vmn", tagd.app_name, "root_verinfo"
            )
            path = os.path.join(dir_path, f"{tagd.root_version}.yml")
        else:
            dir_path = os.path.join(self.repo_path, ".vmn", tagd.app_name, "verinfo")
            path = os.path.join(dir_path, f"{tagd.verstr}.yml")

        ver_infos = {}
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
        if root_context:
            dir_path = os.path.join(self.repo_path, ".vmn", app_name, "root_verinfo")
        else:
            dir_path = os.path.join(self.repo_path, ".vmn", app_name, "verinfo")

        files = glob.glob(os.path.join(dir_path, "*"))

        # sort the files by modification date
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
