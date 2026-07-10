#!/usr/bin/env python3
"""Pure version serialization / deserialization / formatting logic.

These were originally static methods on VMNBackend. They are pure functions
that only depend on constants and dataclasses — no I/O, no VCS.
"""
import re

from version_stamp.core.constants import (
    VMN_OLD_REGEX,
    VMN_OLD_TAG_REGEX,
    VMN_ROOT_TAG_REGEX,
    VMN_ROOT_VERSION_REGEX,
    VMN_TAG_REGEX,
    VMN_VERSION_REGEX,
)
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.models import TagProps, VersionProps
from version_stamp.core.utils import WrongTagFormatException


def app_name_to_tag_name(app_name):
    return app_name.replace("/", "-")


def tag_name_to_app_name(tag_app_name):
    return tag_app_name.replace("-", "/")


def gen_unique_id(verstr, hash):
    return f"{verstr}+{hash}"


def get_utemplate_formatted_version(raw_vmn_version, template, hide_zero_hotfix):
    props = deserialize_vmn_version(raw_vmn_version)

    if props.hotfix == 0 and hide_zero_hotfix:
        props.hotfix = None

    octats = (
        "major",
        "minor",
        "patch",
        "hotfix",
        "prerelease",
        "rcn",
        "buildmetadata",
    )

    formatted_version = ""
    for octat in octats:
        val = getattr(props, octat)
        if val is None:
            continue

        if (
            f"{octat}_template" in template
            and template[f"{octat}_template"] is not None
        ):
            d = {octat: val}
            if "rcn" in d and props.old_ver_format:
                continue

            if "prerelease" in d and d["prerelease"] == "release":
                continue

            formatted_version = (
                f"{formatted_version}"
                f"{template[f'{octat}_template'].format(**d)}"
            )

    if (
        props.dev_commit is not None
        and "dev_commit_template" in template
        and template["dev_commit_template"] is not None
    ):
        formatted_version += template["dev_commit_template"].format(
            dev_commit=props.dev_commit, dev_diff_hash=props.dev_diff_hash
        )

    return formatted_version


def get_root_app_name_from_name(name):
    root_app_name = name.split("/")
    if len(root_app_name) == 1:
        return None

    return "/".join(root_app_name[:-1])


def serialize_vmn_tag_name(app_name, verstr):
    tag_app_name = app_name_to_tag_name(app_name)
    tag_name = f"{tag_app_name}_{verstr}"

    try:
        props = deserialize_tag_name(tag_name)
        if props.hotfix == 0:
            # tags are always without zero hotfix
            verstr = serialize_vmn_version(verstr, hide_zero_hotfix=True)
            tag_name = f"{tag_app_name}_{verstr}"
            props = deserialize_tag_name(tag_name)
    except Exception:
        err = f"Tag {tag_name} doesn't comply with: {VMN_TAG_REGEX} format"
        VMN_LOGGER.error(err)
        raise RuntimeError(err)

    return tag_name


def serialize_vmn_version(
    base_verstr,
    prerelease=None,
    rcn=None,
    buildmetadata=None,
    hide_zero_hotfix=False,
    dev_commit=None,
    dev_diff_hash=None,
):
    props = deserialize_vmn_version(base_verstr)
    base_verstr = serialize_vmn_base_version(
        props.major,
        props.minor,
        props.patch,
        props.hotfix,
        hide_zero_hotfix=hide_zero_hotfix,
    )

    vmn_version = base_verstr

    if props.prerelease != "release":
        if prerelease is not None:
            VMN_LOGGER.warning(
                "Tried to serialize verstr containing "
                "prerelease component but also tried to append"
                " another prerelease component. Will ignore it"
            )

        prerelease = props.prerelease
        if not props.old_ver_format:
            rcn = props.rcn

    if props.buildmetadata is not None:
        if prerelease is not None:
            VMN_LOGGER.warning(
                "Tried to serialize verstr containing "
                "buildmetadata component but also tried to append"
                " another buildmetadata component. Will ignore it"
            )

        buildmetadata = props.buildmetadata

    if prerelease is not None:
        vmn_version = f"{vmn_version}-{prerelease}"

        if rcn is not None:
            vmn_version = f"{vmn_version}.{rcn}"

    if props.dev_commit is not None:
        if dev_commit is not None:
            VMN_LOGGER.warning(
                "Tried to serialize verstr containing "
                "dev component but also tried to append"
                " another dev component. Will ignore it"
            )
        dev_commit = props.dev_commit
        dev_diff_hash = props.dev_diff_hash

    if dev_commit is not None:
        vmn_version = f"{vmn_version}-dev.{dev_commit}.{dev_diff_hash}"

    if buildmetadata is not None:
        vmn_version = f"{vmn_version}+{buildmetadata}"

    return vmn_version


def serialize_vmn_base_version(
    major, minor, patch, hotfix=None, hide_zero_hotfix=None
):
    if hide_zero_hotfix and hotfix == 0:
        hotfix = None

    vmn_version = f"{major}.{minor}.{patch}"
    if hotfix is not None:
        vmn_version = f"{vmn_version}.{hotfix}"

    return vmn_version


def get_base_vmn_version(some_verstr, hide_zero_hotfix=None):
    props = deserialize_vmn_version(some_verstr)

    vmn_version = serialize_vmn_base_version(
        props.major,
        props.minor,
        props.patch,
        props.hotfix,
        hide_zero_hotfix,
    )

    return vmn_version


def deserialize_tag_name(some_tag):
    app_name = None
    old_tag_format = False

    match = re.search(VMN_ROOT_TAG_REGEX, some_tag)
    if match is not None:
        gdict = match.groupdict()
        app_name = gdict["app_name"]
    else:
        match = re.search(VMN_TAG_REGEX, some_tag)
        if match is None:
            match = re.search(VMN_OLD_TAG_REGEX, some_tag)
            if match is None:
                raise WrongTagFormatException()

            old_tag_format = True

        gdict = match.groupdict()
        app_name = tag_name_to_app_name(gdict["app_name"])

    res = app_name_to_tag_name(app_name)
    verstr = some_tag.split(f"{res}_")[1]

    ver_props = deserialize_vmn_version(verstr)

    ret = TagProps(
        types=ver_props.types,
        root_version=ver_props.root_version,
        major=ver_props.major,
        minor=ver_props.minor,
        patch=ver_props.patch,
        hotfix=ver_props.hotfix,
        prerelease=ver_props.prerelease,
        rcn=ver_props.rcn,
        buildmetadata=ver_props.buildmetadata,
        dev_commit=ver_props.dev_commit,
        dev_diff_hash=ver_props.dev_diff_hash,
        old_ver_format=ver_props.old_ver_format,
        app_name=app_name,
        old_tag_format=old_tag_format,
        verstr=verstr,
    )

    return ret


def deserialize_vmn_version(verstr):
    ret = VersionProps()

    match = re.search(VMN_ROOT_VERSION_REGEX, verstr)
    if match is not None:
        gdict = match.groupdict()

        int(gdict["version"])
        ret.root_version = gdict["version"]
        ret.types.add("root")

        return ret

    match = re.search(VMN_VERSION_REGEX, verstr)
    old_ver_format = False
    if match is None:
        match = re.search(VMN_OLD_REGEX, verstr)
        if match is None:
            raise WrongTagFormatException()

        old_ver_format = True

    gdict = match.groupdict()
    if old_ver_format:
        gdict["rcn"] = -1
        ret.old_ver_format = True

    ret.major = int(gdict["major"])
    ret.minor = int(gdict["minor"])
    ret.patch = int(gdict["patch"])
    ret.hotfix = 0

    if gdict["hotfix"] is not None:
        ret.hotfix = int(gdict["hotfix"])

    if gdict["prerelease"] is not None:
        ret.prerelease = gdict["prerelease"]
        ret.rcn = int(gdict["rcn"])
        ret.types.add("prerelease")

    if gdict.get("dev_commit") is not None:
        ret.dev_commit = gdict["dev_commit"]
        ret.dev_diff_hash = gdict["dev_diff_hash"]
        ret.types.add("dev")

    if gdict["buildmetadata"] is not None:
        ret.buildmetadata = gdict["buildmetadata"]
        ret.types.add("buildmetadata")

    return ret


def deserialize_vmn_tag_name(vmn_tag):
    try:
        return deserialize_tag_name(vmn_tag)
    except WrongTagFormatException as exc:
        VMN_LOGGER.error(
            f"Tag {vmn_tag} doesn't comply to vmn version format",
            exc_info=True,
        )
        raise exc
    except Exception as exc:
        VMN_LOGGER.error(
            f"Failed to deserialize tag {vmn_tag}",
            exc_info=True,
        )
        raise exc


def parse_conventional_commit_message(message):
    from version_stamp.core.constants import CONVENTIONAL_COMMIT_PATTERN
    match = CONVENTIONAL_COMMIT_PATTERN.match(message)
    if match:
        return match.groupdict()
    else:
        raise ValueError("Invalid commit message format")


def compare_release_modes(r1, r2):
    version_map = {
        "major": 3,
        "minor": 2,
        "patch": 1,
        "micro": 0,
    }

    return version_map[r1] >= version_map[r2]
