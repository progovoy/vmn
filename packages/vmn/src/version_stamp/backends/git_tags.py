#!/usr/bin/env python3
"""Git backend mixin: tag lookup, version info retrieval."""
from version_stamp.core.constants import (
    MAX_COMMIT_SEARCH_ITERATIONS,
    RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE,
    RELATIVE_TO_CURRENT_VCS_POSITION_TYPE,
    RELATIVE_TO_GLOBAL_TYPE,
    VMN_USER_NAME,
)
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.utils import _clean_split_result
from version_stamp.core.version_math import (
    app_name_to_tag_name,
    serialize_vmn_tag_name,
)


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

        if self._is_shallow():
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
            vi["tag_object"]
            for vi in ver_infos.values()
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

        tag_name_prefix = app_name_to_tag_name(app_name)
        tag_names = self._list_tags(f"{tag_name_prefix}_*")

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
        final_list_of_tag_names = self._sorted_tag_names_from_ver_infos(
            ver_infos, filter_none=True
        )

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
        return self._list_tags(tag_prefix_filter) or None

    @measure_runtime_decorator
    def get_latest_available_tag(self, tag_prefix_filter):
        tnames = self.get_latest_available_tags(tag_prefix_filter)
        if tnames is None:
            return None

        return tnames[-1]

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
                tagname = serialize_vmn_tag_name(app_name, verstr)
                tagname, ver_info_c = self.parse_tag_message(tagname)
                if ver_info_c["tag_object"]:
                    ver_infos[tagname] = ver_info_c

                    cleaned_tags = self.get_all_brother_tags(tagname)
                    cleaned_tags.pop(tagname)
                    cleaned_tags = cleaned_tags.keys()
            except Exception:
                VMN_LOGGER.debug(f"Skipped on {hexsha} commit")

        ver_infos.update(self._parse_vmn_tags(cleaned_tags))
        return ver_infos

    @measure_runtime_decorator
    def get_all_commit_tags(self, hexsha="HEAD"):
        if hexsha is None:
            hexsha = "HEAD"

        cmd = ["--points-at", hexsha]
        tags = _clean_split_result(self._be.git.tag(*cmd).split("\n"))
        return self._parse_vmn_tags(tags)

    @measure_runtime_decorator
    def get_all_brother_tags(self, tag_name):
        try:
            sha = self.changeset(tag=tag_name)
            if sha is None:
                return {}
            ver_infos = self.get_all_commit_tags(sha)
        except Exception:
            VMN_LOGGER.debug(
                f"Failed to get brother tags for tag: {tag_name}. "
                f"Logged exception: ",
                exc_info=True,
            )
            return {}

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
            return tag_name, {}

        return tag_name, ver_infos
