"""The record format's names: record/dep/app path segments, the metadata and
patch file names, and a record directory's patch files.

The same names and file bytes as ``vmn_exp.storage.files``. Reading differs
at the edges: a patch path that is not a readable file is skipped there
(``isfile``) but raises here unless missing, as core's local store always did.
"""
import os

from version_stamp.core.utils import atomic_write, valid_app_path, valid_path_component

METADATA_FILE = "metadata.yml"
# (patches key, file name, binary?)
PATCH_FILES = (
    ("working_tree", "working_tree.patch", False),
    ("local_commits", "local_commits.patch", False),
    ("untracked_files", "untracked_files.tar.gz", True),
)


def safe_verstr(verstr):
    """*verstr* as a record directory/key name; ValueError if it would walk."""
    if not valid_path_component(verstr):
        raise ValueError(f"Invalid record name: {verstr!r}")
    return verstr.replace("+", "_plus_")


def unsafe_verstr(name):
    return name.replace("_plus_", "+")


def safe_dep_name(dep_path):
    return dep_path.replace(os.sep, "_").replace("/", "_")


def checked_app_path(app_name):
    """*app_name* unchanged; ValueError if it is not a relative app path."""
    if not valid_app_path(app_name):
        raise ValueError(f"Invalid app name: {app_name!r}")
    return app_name


def apply_metadata_updates(metadata, updates):
    """*metadata* with *updates* merged in; a None value drops the field."""
    for key, value in updates.items():
        if value is None:
            metadata.pop(key, None)
        else:
            metadata[key] = value
    return metadata


def read_file(path):
    """*path*'s bytes, or None when it (or its directory) does not exist."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except (FileNotFoundError, NotADirectoryError):
        return None


def write_patches_to_dir(directory, patches):
    """Write the patch files *patches* carries and drop the ones it lacks."""
    for key, filename, binary in PATCH_FILES:
        path = os.path.join(directory, filename)
        content = patches.get(key)
        if not content:
            if os.path.lexists(path):
                os.unlink(path)
            continue
        atomic_write(path, content if binary else content.encode("utf-8"))


def read_patches_from_dir(directory):
    patches = {}
    for key, filename, binary in PATCH_FILES:
        data = read_file(os.path.join(directory, filename))
        if data is not None:
            patches[key] = data if binary else data.decode("utf-8")
    return patches
