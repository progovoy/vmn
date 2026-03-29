#!/usr/bin/env python3
import os

from version_stamp.core.constants import JINJA_TAG_RE
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


class WrongTagFormatException(Exception):
    pass
