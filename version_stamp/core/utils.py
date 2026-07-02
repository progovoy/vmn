#!/usr/bin/env python3
import os

from version_stamp.core.constants import BRANCH_CONF_DIR, JINJA_TAG_RE
from version_stamp.core.logging import VMN_LOGGER


def _clean_split_result(items):
    """Remove the single empty string that split() produces from empty output."""
    if len(items) == 1 and items[0] == "":
        items.pop(0)
    return items


def comment_out_jinja(text: str) -> str:
    """
    Wrap every live tag so it survives rendering, e.g.
        {{ foo }}  →  {% raw %}{{ foo }}{% endraw %}
    """
    return JINJA_TAG_RE.sub(lambda m: '{% raw %}' + m.group(1) + '{% endraw %}', text)


def resolve_root_path():
    cwd = os.getcwd()
    if "VMN_WORKING_DIR" in os.environ:
        cwd = os.environ["VMN_WORKING_DIR"]

    root_path = os.path.realpath(os.path.expanduser(cwd))

    exist = os.path.exists(os.path.join(root_path, ".git"))
    exist = exist or os.path.exists(os.path.join(root_path, ".vmn"))
    while not exist:
        try:
            prev_path = root_path
            root_path = os.path.realpath(os.path.join(root_path, ".."))
            if prev_path == root_path:
                raise RuntimeError()

            exist = os.path.exists(os.path.join(root_path, ".git"))
            exist = exist or os.path.exists(os.path.join(root_path, ".vmn"))
        except Exception:
            VMN_LOGGER.debug("Logged exception: ", exc_info=True)
            root_path = None
            break
    if root_path is None:
        raise RuntimeError("Running from an unmanaged directory")

    return root_path


def branch_to_conf_prefix(branch_name):
    """Sanitize branch name for use in conf filenames (abc/feat → abc-feat)."""
    return branch_name.replace("/", "-")


def _conf_basename(root):
    return "root_conf.yml" if root else "conf.yml"


def branch_conf_canonical_path(app_dir_path, branch, root=False):
    """Canonical layout: {app_dir}/branch_conf/{branch as dirs}/(root_)conf.yml"""
    return os.path.join(
        app_dir_path,
        BRANCH_CONF_DIR,
        branch.replace("/", os.sep),
        _conf_basename(root),
    )


def branch_conf_flat_path(app_dir_path, branch, root=False):
    """Flat layout: {app_dir}/{branch-with-dashes}_(root_)conf.yml"""
    return os.path.join(
        app_dir_path,
        f"{branch_to_conf_prefix(branch)}_{_conf_basename(root)}",
    )


def branch_conf_legacy_path(app_dir_path, branch, root=False):
    """Legacy nested layout: {app_dir}/{seg0}/../{leaf}_(root_)conf.yml"""
    segments = branch.split("/")
    return os.path.join(
        app_dir_path,
        *segments[:-1],
        f"{segments[-1]}_{_conf_basename(root)}",
    )


def resolve_branch_conf_path(app_dir_path, branch, root=False):
    """Resolve a branch-specific conf file, supporting all layouts.

    Precedence: canonical > flat > legacy. Falls back to the default
    (root_)conf.yml with convention None when no branch conf exists.
    """
    if branch:
        for convention, path_fn in (
            ("canonical", branch_conf_canonical_path),
            ("flat", branch_conf_flat_path),
            ("legacy", branch_conf_legacy_path),
        ):
            path = path_fn(app_dir_path, branch, root=root)
            if os.path.isfile(path):
                return path, convention

    return os.path.join(app_dir_path, _conf_basename(root)), None


class WrongTagFormatException(Exception):
    pass
