#!/usr/bin/env python3
"""Git backend mixin: tag lookup, version info retrieval."""
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


def _parse_vmn_commit_line(line):
    """``(hexsha, decorations)`` of a ``%H,,,%D`` git log line."""
    commit_hex, decorations = line.split(",,,", 1)
    return commit_hex, _clean_split_result(decorations.split(","))


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
        tagged = [
            vi
            for vi in ver_infos.values()
            if not filter_none or vi["tag_object"] is not None
        ]
        tagged.sort(key=lambda vi: vi["tagged_date"], reverse=True)
        return [vi["tag_object"].name for vi in tagged]

    @measure_runtime_decorator
    def _get_first_reachable_vmn_stamp_tag_list(self, app_name, cmd_suffix, msg_filter):
        cobj, ver_infos = self._get_top_vmn_commit(app_name, cmd_suffix, msg_filter)
        if not ver_infos and cobj is not None:
            cobj, ver_infos = self._walk_back_to_tagged_vmn_commit(
                app_name, f"{cobj.hexsha}~1", msg_filter
            )

        tag_names = self._sorted_tag_names_from_ver_infos(ver_infos)

        return tag_names, cobj, ver_infos

    def _walk_back_to_tagged_vmn_commit(self, app_name, start, msg_filter):
        """First vmn commit from *start* back whose tags parse, in one git log."""
        commit_hex = None
        searched = 0
        for commit_hex, tags in self._stream_vmn_commits(
            msg_filter, start, MAX_COMMIT_SEARCH_ITERATIONS
        ):
            searched += 1
            ver_infos = self.get_all_commit_tags_log_impl(commit_hex, tags, app_name)
            if ver_infos:
                return self.get_commit_object_from_commit_hex(commit_hex), ver_infos

        if searched < MAX_COMMIT_SEARCH_ITERATIONS:
            return None, {}

        VMN_LOGGER.warning(
            "Probable bug: vmn failed to find "
            f"vmn's commit after {MAX_COMMIT_SEARCH_ITERATIONS} iterations."
        )
        return self.get_commit_object_from_commit_hex(commit_hex), {}

    def _stream_vmn_commits(self, msg_filter, start, max_count):
        """Yield ``(hexsha, decorations)`` of vmn commits, newest first."""
        proc = self._be.git.log(
            *self._vmn_commit_log_args(msg_filter, f"-n{max_count}", start),
            as_process=True,
        )
        try:
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    yield _parse_vmn_commit_line(line)
        finally:
            proc.proc.kill()
            proc.proc.wait()

    @measure_runtime_decorator
    def _get_shallow_first_reachable_vmn_stamp_tag_list(
        self, app_name, cmd_suffix, msg_filter
    ):
        cobj, ver_infos = self._get_top_vmn_commit(app_name, cmd_suffix, msg_filter)

        if ver_infos:
            tag_names = self._sorted_tag_names_from_ver_infos(ver_infos)

            return tag_names, cobj, ver_infos

        tag_name_prefix = VMNBackend.app_name_to_tag_name(app_name)
        tag_names = self._list_tags(f"{tag_name_prefix}_*")

        if not tag_names:
            return tag_names, cobj, ver_infos

        latest_tag = tag_names[-1]
        head_commit = self._be.head.commit
        head_date = head_commit.committed_date
        for tname in reversed(tag_names):
            tname, o = self.get_tag_object_from_tag_name(tname)
            if o:
                if (
                    head_commit.hexsha != o.commit.hexsha
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

        found_commit = found_tag.commit
        ver_infos = self.get_all_commit_tags(found_commit.hexsha)
        final_list_of_tag_names = self._sorted_tag_names_from_ver_infos(
            ver_infos, filter_none=True
        )

        return final_list_of_tag_names, found_commit, ver_infos

    @measure_runtime_decorator
    def _get_top_vmn_commit(self, app_name, cmd_suffix, msg_filter):
        cmd = self._vmn_commit_log_args(msg_filter, "-1", cmd_suffix)
        log_res = _clean_split_result(self._be.git.log(*cmd).split("\n"))

        if not log_res:
            return None, {}

        commit_hex, tags = _parse_vmn_commit_line(log_res[0])
        ver_infos = self.get_all_commit_tags_log_impl(commit_hex, tags, app_name)

        cobj = self.get_commit_object_from_commit_hex(commit_hex)

        return cobj, ver_infos

    @staticmethod
    def _vmn_commit_log_args(msg_filter, limit, start):
        return [
            f"--grep={msg_filter}",
            limit,
            f"--author={VMN_USER_NAME}",
            "--pretty=%H,,,%D",
            "--decorate=short",
            start,
        ]

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
                tagname = VMNBackend.serialize_vmn_tag_name(app_name, verstr)
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
