#!/usr/bin/env python3
"""File-level helpers shared by the snapshot storage backends: record file
names, atomic writes and patch files (log naming/parsing: core.experiment_logfiles)."""
import os
import shutil
import tempfile

# Log file naming and parsing live in core, shared with the experiment index.
from version_stamp.core.experiment_logfiles import (  # noqa: F401  (re-exported)
    LEGACY_LOG_FILE,
    group_log_names,
    is_log_file,
    log_object_name,
    log_writer_and_seq,
    parse_jsonl,
)
from version_stamp.core.utils import valid_app_path, valid_path_component

METADATA_FILE = "metadata.yml"
# The derived experiment-index cache, beside the records it summarizes.
INDEX_CACHE_FILE = ".index.sqlite"
# (patches key, file name, binary?)
PATCH_FILES = (
    ("working_tree", "working_tree.patch", False),
    ("local_commits", "local_commits.patch", False),
    ("untracked_files", "untracked_files.tar.gz", True),
)
# Rewritten while a run lives, so a copy fetched from a remote is stale at once.
VOLATILE_FILES = ("run_state.yml",)


def safe_verstr(verstr):
    """*verstr* as a record directory/key name; ValueError if it would walk."""
    if not valid_path_component(verstr):
        raise ValueError(f"Invalid record name: {verstr!r}")
    return verstr.replace("+", "_plus_")


def checked_app_path(app_name):
    """*app_name* unchanged; ValueError if it is not a relative app path."""
    if not valid_app_path(app_name):
        raise ValueError(f"Invalid app name: {app_name!r}")
    return app_name


def unsafe_verstr(name):
    return name.replace("_plus_", "+")


def safe_dep_name(dep_path):
    return dep_path.replace(os.sep, "_").replace("/", "_")


def is_volatile_file(name):
    return name in VOLATILE_FILES or is_log_file(name)


def valid_artifact_path(name):
    """Whether *name* is a safe artifact path relative to the run's artifacts:
    ``a/b/c.txt`` yes; absolute, ``..``, ``.``, empty components, backslashes
    or NUL no."""
    if not isinstance(name, str):
        return False
    return all(valid_path_component(part) for part in name.split("/"))


def artifact_name_for(src_path, name=None):
    """The stored name of an artifact: *name*, else *src_path*'s basename.
    ValueError for a name that would leave the run's artifacts."""
    name = os.path.basename(src_path) if name is None else name
    if not valid_artifact_path(name):
        raise ValueError(f"Invalid artifact name: {name!r}")
    return name


def artifact_file_path(art_dir, name):
    """The local path of artifact *name* (already validated) under *art_dir*."""
    return os.path.join(art_dir, *name.split("/"))


def list_artifact_tree(art_dir):
    """``[{"name", "size"}]`` of every file under *art_dir*, nested names
    ``/``-joined, name-ordered."""
    found = []
    for dirpath, _, filenames in os.walk(art_dir):
        rel = os.path.relpath(dirpath, art_dir)
        prefix = "" if rel == "." else rel.replace(os.sep, "/") + "/"
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            if os.path.isfile(path):
                found.append({"name": prefix + filename, "size": os.path.getsize(path)})
    return sorted(found, key=lambda a: a["name"])


def apply_metadata_updates(metadata, updates):
    """*metadata* with *updates* merged in; a None value drops the field."""
    for key, value in updates.items():
        if value is None:
            metadata.pop(key, None)
        else:
            metadata[key] = value
    return metadata


def log_sizes_of(files):
    """``{writer: total bytes}`` over ``(name, size)`` pairs of a record's files,
    counting only the log files a reader sees (not what a compaction superseded)."""
    files = dict(files)
    sizes = {"": files[LEGACY_LOG_FILE]} if LEGACY_LOG_FILE in files else {}
    for writer, names in group_log_names(files).items():
        sizes[writer] = sum(files[name] for name in names)
    return sizes


def flatten_logs(logs_by_writer):
    """The legacy ``log.yml`` entries (writer ``""``) first, then writers by name,
    stably sorted by timestamp."""
    entries = []
    for writer in sorted(logs_by_writer):
        entries.extend(logs_by_writer[writer])
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return entries


def atomic_write(path, data):
    """Write *data* so readers see the old file or the new one, never half."""
    directory, name = os.path.split(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _same_bytes(path, data):
    try:
        if os.path.getsize(path) != len(data):
            return False
        with open(path, "rb") as f:
            return f.read() == data
    except OSError:
        return False


def _link_or_copy(src, dst):
    if os.path.lexists(dst):
        os.unlink(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _same_size(path, data):
    try:
        return os.path.getsize(path) == len(data)
    except OSError:
        return False


def _identical(path, data, trusted):
    """Whether *path* holds *data*. A *trusted* source (same ``diff_hash``)
    already has the same content, so its size is proof enough."""
    return _same_size(path, data) if trusted else _same_bytes(path, data)


def write_patches_to_dir(directory, patches, link_from=()):
    """Write the patch files *patches* carries and drop the ones it lacks.

    An identical file in one of the *link_from* ``(directory, trusted)``
    sources is hard-linked rather than written again, so runs of the same code
    share their patches.
    """
    for key, filename, binary in PATCH_FILES:
        path = os.path.join(directory, filename)
        content = patches.get(key)
        if not content:
            if os.path.lexists(path):
                os.unlink(path)
            continue
        data = content if binary else content.encode("utf-8")
        source = next(
            (
                os.path.join(src, filename)
                for src, trusted in link_from
                if _identical(os.path.join(src, filename), data, trusted)
            ),
            None,
        )
        if source:
            _link_or_copy(source, path)
        else:
            atomic_write(path, data)


def read_patches_from_dir(directory):
    patches = {}
    for key, filename, binary in PATCH_FILES:
        path = os.path.join(directory, filename)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                data = f.read()
            patches[key] = data if binary else data.decode("utf-8")
    return patches
