#!/usr/bin/env python3
"""Git backend mixin: tag lookup, version info retrieval."""
import os

import yaml

from version_stamp.backends.base import VMNBackend
from version_stamp.core.constants import (
    MAX_COMMIT_SEARCH_ITERATIONS,
    RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE,
    RELATIVE_TO_CURRENT_VCS_POSITION_TYPE,
    RELATIVE_TO_GLOBAL_TYPE,
    VMN_USER_NAME,
)
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.utils import _clean_split_result


class GitTagsMixin:
    """Methods for tag/version lookup. Mixed into GitBackend."""

    @measure_runtime_decorator
    def get_latest_stamp_tags(
        self, app_name, root_context, type=RELATIVE_TO_GLOBAL_TYPE
    ):
        if root_context:
            msg_filter = f"^{app_name}/.*: Stamped"
        else:
            msg_filter = f"^{app_name}: Stamped"

        if type == RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE:
            cmd_suffix = f"refs/heads/{self.active_branch}"
        elif type == RELATIVE_TO_CURRENT_VCS_POSITION_TYPE:
            cmd_suffix = "HEAD"
        else:
            cmd_suffix = "--branches"

        shallow = os.path.exists(os.path.join(self._be.common_dir, "shallow"))
        if shallow:
            self.perform_cached_fetch()
            (
                tag_names,
                cobj,
                ver_infos,
            ) = self._get_shallow_first_reachable_vmn_stamp_tag_list(
                app_name,
                cmd_suffix,
                msg_filter,
            )
        else:
            tag_names, cobj, ver_infos = self._get_first_reachable_vmn_stamp_tag_list(
                app_name, cmd_suffix, msg_filter
            )

        return tag_names, cobj, ver_infos

    @staticmethod
    def _sorted_tag_names_from_ver_infos(ver_infos, filter_none=False):
        """Extract tag names from ver_infos, sorted newest first by tagged_date."""
        tag_objects = [
            vi["tag_object"] for vi in ver_infos.values()
            if not filter_none or vi["tag_object"] is not None
        ]
        tag_objects.sort(key=lambda t: t.object.tagged_date, reverse=True)
        return [t.name for t in tag_objects]

    @measure_runtime_decorator
    def _get_first_reachable_vmn_stamp_tag_list(self, app_name, cmd_suffix, msg_filter):
        cobj, ver_infos = self._get_top_vmn_commit(app_name, cmd_suffix, msg_filter)
        bug_limit = MAX_COMMIT_SEARCH_ITERATIONS
        bug_limit_c = 0
        while not ver_infos and bug_limit_c < bug_limit:
            if cobj is None:
                break

            cmd_suffix = f"{cobj.hexsha}~1"
            cobj, ver_infos = self._get_top_vmn_commit(app_name, cmd_suffix, msg_filter)

            bug_limit_c += 1
            if bug_limit_c == bug_limit:
                VMN_LOGGER.warning(
                    "Probable bug: vmn failed to find "
                    f"vmn's commit after {bug_limit} iterations."
                )
                ver_infos = {}
                break

        tag_names = self._sorted_tag_names_from_ver_infos(ver_infos)

        return tag_names, cobj, ver_infos

    @measure_runtime_decorator
    def _get_shallow_first_reachable_vmn_stamp_tag_list(
        self, app_name, cmd_suffix, msg_filter
    ):
        cobj, ver_infos = self._get_top_vmn_commit(app_name, cmd_suffix, msg_filter)

        if ver_infos:
            tag_names = self._sorted_tag_names_from_ver_infos(ver_infos)

            return tag_names, cobj, ver_infos

        tag_name_prefix = VMNBackend.app_name_to_tag_name(app_name)
        cmd = ["--sort", "taggerdate", "--list", f"{tag_name_prefix}_*"]
        tag_names = _clean_split_result(self._be.git.tag(*cmd).split("\n"))

        if not tag_names:
            return tag_names, cobj, ver_infos

        latest_tag = tag_names[-1]
        head_date = self._be.head.commit.committed_date
        for tname in reversed(tag_names):
            tname, o = self.get_tag_object_from_tag_name(tname)
            if o:
                if (
                    self._be.head.commit.hexsha != o.commit.hexsha
                    and head_date < o.object.tagged_date
                ):
                    continue

                latest_tag = tname
                break

        try:
            found_tag = self._be.tag(f"refs/tags/{latest_tag}")
        except Exception:
            VMN_LOGGER.error(f"Failed to get tag object from tag name: {latest_tag}")
            return [], cobj, ver_infos

        ver_infos = self.get_all_commit_tags(found_tag.commit.hexsha)
        final_list_of_tag_names = self._sorted_tag_names_from_ver_infos(ver_infos, filter_none=True)

        return final_list_of_tag_names, found_tag.commit, ver_infos

    @measure_runtime_decorator
    def _get_top_vmn_commit(self, app_name, cmd_suffix, msg_filter):
        cmd = [
            f"--grep={msg_filter}",
            "-1",
            f"--author={VMN_USER_NAME}",
            "--pretty=%H,,,%D",
            "--decorate=short",
            cmd_suffix,
        ]
        log_res = _clean_split_result(self._be.git.log(*cmd).split("\n"))

        if not log_res:
            return None, {}

        items = log_res[0].split(",,,")
        tags = _clean_split_result(items[1].split(","))

        commit_hex = items[0]
        ver_infos = self.get_all_commit_tags_log_impl(commit_hex, tags, app_name)

        cobj = self.get_commit_object_from_commit_hex(commit_hex)

        return cobj, ver_infos

    @measure_runtime_decorator
    def get_latest_available_tags(self, tag_prefix_filter):
        cmd = ["--sort", "taggerdate", "--list", tag_prefix_filter]
        tag_names = _clean_split_result(self._be.git.tag(*cmd).split("\n"))

        if not tag_names:
            return None

        return tag_names

    @measure_runtime_decorator
    def get_latest_available_tag(self, tag_prefix_filter):
        tnames = self.get_latest_available_tags(tag_prefix_filter)
        if tnames is None:
            return None

        return tnames[-1]

    @measure_runtime_decorator
    def get_commit_object_from_branch_name(self, bname):
        # TODO:: Unfortunately, need to spend o(N) here
        for branch in self._be.branches:
            if bname != branch.name:
                continue

            return branch.commit

        raise RuntimeError(
            f"Somehow did not find a branch commit object for branch: {bname}"
        )

    @measure_runtime_decorator
    def get_tag_object_from_tag_name(self, tname):
        try:
            o = self._be.tag(f"refs/tags/{tname}")
        except Exception:
            VMN_LOGGER.debug("Logged exception: ", exc_info=True)
            # Backward compatability code for vmn 0.3.9:
            try:
                _tag_name = f"{tname}.0"
                o = self._be.tag(f"refs/tags/{_tag_name}")
            except Exception:
                VMN_LOGGER.debug("Logged exception: ", exc_info=True)
                return tname, None

        try:
            if o.commit.author.name != "vmn":
                return tname, None
        except Exception:
            VMN_LOGGER.debug("Exception info: ", exc_info=True)
            return tname, None

        if o.tag is None:
            return tname, None

        return tname, o

    @measure_runtime_decorator
    def get_all_commit_tags_log_impl(self, hexsha, tags, app_name):
        cleaned_tags = []
        for t in tags:
            if "tag:" not in t:
                continue

            tname = t.split("tag:")[1].strip()
            cleaned_tags.append(tname)

        ver_infos = {}
        if not cleaned_tags:
            # Maybe rebase or tag was removed. Will handle the rebase case here
            try:
                commit_obj = self.get_commit_object_from_commit_hex(hexsha)
                verstr = commit_obj.message.split(" version ")[1].strip()
                tagname = f"{app_name}_{verstr}"
                tagname, ver_info_c = self.parse_tag_message(tagname)
                if ver_info_c["tag_object"]:
                    ver_infos[tagname] = ver_info_c

                    cleaned_tags = self.get_all_brother_tags(tagname)
                    cleaned_tags.pop(tagname)
                    cleaned_tags = cleaned_tags.keys()
            except Exception:
                VMN_LOGGER.debug(f"Skipped on {hexsha} commit")

        for tname in cleaned_tags:
            tname, ver_info_c = self.parse_tag_message(tname)
            if ver_info_c["ver_info"] is None:
                VMN_LOGGER.debug(
                    f"Probably non-vmn tag - {tname} with tag msg: {ver_info_c['ver_info']}. Skipping ",
                    exc_info=True,
                )
                continue

            ver_infos[tname] = ver_info_c

        return ver_infos

    @measure_runtime_decorator
    def get_all_commit_tags(self, hexsha="HEAD"):
        if hexsha is None:
            hexsha = "HEAD"

        cmd = ["--points-at", hexsha]
        tags = _clean_split_result(self._be.git.tag(*cmd).split("\n"))

        ver_infos = {}
        for t in tags:
            t, ver_info_c = self.parse_tag_message(t)
            if ver_info_c["ver_info"] is None:
                VMN_LOGGER.debug(
                    f"Probably non-vmn tag - {t} with tag msg: {ver_info_c['ver_info']}. Skipping ",
                    exc_info=True,
                )
                continue

            ver_infos[t] = ver_info_c

        return ver_infos

    @measure_runtime_decorator
    def get_all_brother_tags(self, tag_name):
        try:
            sha = self.changeset(tag=tag_name)
            ver_infos = self.get_all_commit_tags(sha)
        except Exception:
            VMN_LOGGER.debug(
                f"Failed to get brother tags for tag: {tag_name}. "
                f"Logged exception: ",
                exc_info=True,
            )
            return []

        return ver_infos

    @measure_runtime_decorator
    def get_tag_version_info(self, tag_name):
        ver_infos = {}
        tag_name, commit_tag_obj = self.get_commit_object_from_tag_name(tag_name)

        if commit_tag_obj is None:
            VMN_LOGGER.debug(f"Tried to find {tag_name} but with no success")
            return tag_name, ver_infos

        if commit_tag_obj.author.name != VMN_USER_NAME:
            VMN_LOGGER.debug(f"Corrupted tag {tag_name}: author name is not vmn")
            return tag_name, ver_infos

        # "raw" ver_infos
        ver_infos = self.get_all_brother_tags(tag_name)
        if tag_name not in ver_infos:
            VMN_LOGGER.debug(f"Could not find version info for {tag_name}")
            return tag_name, None

        return tag_name, ver_infos

    @measure_runtime_decorator
    def parse_tag_message(self, tag_name):
        tag_name, tag_obj = self.get_tag_object_from_tag_name(tag_name)

        ret = {"ver_info": None, "tag_object": tag_obj, "commit_object": None}
        if not tag_obj:
            return tag_name, ret

        commit_tag_obj = tag_obj.commit
        if commit_tag_obj is None or commit_tag_obj.author.name != VMN_USER_NAME:
            VMN_LOGGER.debug(f"Corrupted tag {tag_name}: author name is not vmn")
            return tag_name, ret

        ret["commit_object"] = commit_tag_obj

        # TODO:: Check API commit version
        # safe_load discards any text before the YAML document (if present)
        ver_info = yaml.safe_load(tag_obj.object.message)
        if ver_info is None:
            return tag_name, ret

        if not isinstance(ver_info, dict) and ver_info.startswith("Automatic"):
            # Code from vmn 0.3.9
            commit_msg = yaml.safe_load(self._be.commit(tag_name).message)

            if commit_msg is not None and "stamping" in commit_msg:
                commit_msg["stamping"]["app"]["prerelease"] = "release"
                commit_msg["stamping"]["app"]["prerelease_count"] = {}

            ver_info = commit_msg
            if ver_info is None:
                return tag_name, ret

        if "vmn_info" not in ver_info:
            VMN_LOGGER.debug(f"vmn_info key was not found in tag {tag_name}")
            return tag_name, ret

        ret["ver_info"] = ver_info

        return tag_name, ret
