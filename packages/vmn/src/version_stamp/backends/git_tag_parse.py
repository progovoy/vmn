#!/usr/bin/env python3
"""Git backend mixin: listing tags and parsing vmn tag messages."""
from version_stamp.compat.tag_format_039 import (
    parse_automatic_tag_message,
    try_tag_with_dot_zero_suffix,
)
from version_stamp.core.constants import VMN_USER_NAME
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.utils import _clean_split_result, yaml_safe_load


class GitTagParseMixin:
    """Tag listing and tag-message parsing. Mixed into GitBackend."""

    def _list_tags(self, pattern, by_date=True):
        """Tag names matching *pattern*, oldest tagger date first (by_date), else
        in refname order, which skips reading every tag object."""
        sort = ("--sort", "taggerdate") if by_date else ()
        tags = self._be.git.tag(*sort, "--list", pattern)
        return _clean_split_result(tags.split("\n"))

    def _parse_vmn_tags(self, tag_names):
        """``{tag_name: ver_info}`` of the *tag_names* that are vmn tags."""
        ver_infos = {}
        for tname in tag_names:
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
    def get_tag_object_from_tag_name(self, tname):
        try:
            o = self._be.tag(f"refs/tags/{tname}")
        except Exception:
            VMN_LOGGER.debug("Logged exception: ", exc_info=True)
            tname, o = try_tag_with_dot_zero_suffix(self._be, tname)
            if o is None:
                return tname, None

        try:
            if o.commit.author.name != VMN_USER_NAME:
                return tname, None
        except Exception:
            VMN_LOGGER.debug("Exception info: ", exc_info=True)
            return tname, None

        if o.tag is None:
            return tname, None

        return tname, o

    @measure_runtime_decorator
    def parse_tag_message(self, tag_name):
        tag_name, tag_obj = self.get_tag_object_from_tag_name(tag_name)

        ret = {"ver_info": None, "tag_object": tag_obj, "commit_object": None}
        if not tag_obj:
            return tag_name, ret

        # Each TagReference.object/.commit access re-resolves the ref
        tag_data = tag_obj.object
        ret["tagged_date"] = tag_data.tagged_date
        commit_tag_obj = tag_obj.commit
        if commit_tag_obj is None or commit_tag_obj.author.name != VMN_USER_NAME:
            VMN_LOGGER.debug(f"Corrupted tag {tag_name}: author name is not vmn")
            return tag_name, ret

        ret["commit_object"] = commit_tag_obj

        # TODO:: Check API commit version
        # safe_load discards any text before the YAML document (if present)
        ver_info = yaml_safe_load(tag_data.message)
        if ver_info is None:
            return tag_name, ret

        if not isinstance(ver_info, dict):
            ver_info_039 = parse_automatic_tag_message(self._be, tag_name, ver_info)
            if ver_info_039 is not None:
                ver_info = ver_info_039
            if ver_info is None or not isinstance(ver_info, dict):
                return tag_name, ret

        if "vmn_info" not in ver_info:
            VMN_LOGGER.debug(f"vmn_info key was not found in tag {tag_name}")
            return tag_name, ret

        ret["ver_info"] = ver_info

        return tag_name, ret
