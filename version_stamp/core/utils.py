#!/usr/bin/env python3
import datetime
import hashlib
import os

import yaml

from version_stamp.core.constants import BRANCH_CONF_DIR, ISLAND_BRANCH_PREFIX, JINJA_TAG_RE
from version_stamp.core.logging import VMN_LOGGER

# libyaml's loader is ~10x faster than the pure-Python one, and experiment
# listings parse one metadata.yml (and one run_state.yml) per run.
_FAST_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def yaml_safe_load(stream_or_text):
    """``yaml.safe_load`` semantics, on the C loader when libyaml is present."""
    return yaml.load(stream_or_text, Loader=_FAST_SAFE_LOADER)


def parse_record_metadata(raw):
    """A snapshot/experiment record's ``metadata.yml`` dict, or None.

    None for a missing or unparsable file and for legacy ``create_snapshots``
    verinfo files, which share the tree but carry no ``verstr``.
    """
    if not raw:
        return None
    try:
        meta = yaml_safe_load(raw)
    except yaml.YAMLError:
        return None
    return meta if isinstance(meta, dict) and "verstr" in meta else None


_UNSAFE_IN_COMPONENT = ("/", "\\", os.sep, "\0", "..")


def valid_path_component(name):
    """Whether *name* (a verstr, artifact name, ...) stays one path component."""
    return (
        bool(name)
        and name != "."
        and not any(bad in name for bad in _UNSAFE_IN_COMPONENT)
    )


def valid_app_path(app_name):
    """Whether *app_name* is a relative path of real components (``root/svc``)."""
    return bool(app_name) and all(
        valid_path_component(part) for part in app_name.split("/")
    )


def now_iso():
    """UTC now as the ``...Z`` ISO string every vmn record is timestamped with."""
    return (
        datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    )


def sha256_file(abs_path):
    h = hashlib.sha256()
    with open(abs_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


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
    return JINJA_TAG_RE.sub(lambda m: "{% raw %}" + m.group(1) + "{% endraw %}", text)


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


def is_island_branch(branch):
    """True for a private `vmn wt` branch (island/<name>/<source>)."""
    return bool(branch) and branch.startswith(ISLAND_BRANCH_PREFIX)


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
