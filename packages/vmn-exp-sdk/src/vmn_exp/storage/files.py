#!/usr/bin/env python3
"""File-level helpers shared by the snapshot storage backends: record file
names, atomic writes and patch files (log naming/parsing: core.experiment_logfiles)."""
import os
import tempfile

from vmn_exp._base import valid_app_path, valid_path_component

# Log file naming and parsing live in core, shared with the experiment index.
from vmn_exp.core.rewind import drop_rewound
from vmn_exp.core.series_reader import SeriesReader
from vmn_exp.core.logfiles import (  # noqa: F401  (re-exported)
    LEGACY_LOG_FILE,
    LOG_DIR,
    group_log_names,
    is_log_file,
    log_object_name,
    log_writer_and_seq,
    parse_jsonl,
)

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


# A record's stored files: the user's artifacts, and the outputs vmn writes
# itself (``output.log``, logged media and tables). Each is named by its
# record-relative path, ``artifacts/<user path>`` or ``outputs/<path>``, so a
# user artifact can be named anything without colliding with vmn's.
ARTIFACTS_DIR = "artifacts"
OUTPUTS_DIR = "outputs"
FILE_TREES = (ARTIFACTS_DIR, OUTPUTS_DIR)


def valid_relative_path(name):
    """Whether *name* is a safe relative ``a/b/c.txt`` path: absolute, ``..``,
    ``.``, empty components, backslashes or NUL no."""
    if not isinstance(name, str):
        return False
    return all(valid_path_component(part) for part in name.split("/"))


def valid_artifact_path(name):
    """Whether *name* is a safe stored-file path: ``artifacts/…`` or ``outputs/…``."""
    if not isinstance(name, str):
        return False
    tree, _, rest = name.partition("/")
    return tree in FILE_TREES and valid_relative_path(rest)


def user_artifact_path(name):
    """The stored path of the user's artifact *name*."""
    return f"{ARTIFACTS_DIR}/{name}"


def artifact_name_for(src_path, name=None):
    """The stored path of a file: *name*, else ``artifacts/<src_path's basename>``.
    ValueError for a path outside the record's file trees."""
    name = user_artifact_path(os.path.basename(src_path)) if name is None else name
    if not valid_artifact_path(name):
        raise ValueError(f"Invalid artifact name: {name!r}")
    return name


def artifact_file_path(base_dir, name):
    """The local path of *name* (already validated) under *base_dir*."""
    return os.path.join(base_dir, *name.split("/"))


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


def list_record_artifacts(record_dir):
    """``[{"name", "size"}]`` of the files in *record_dir*'s ``artifacts/`` and
    ``outputs/`` trees, named by record-relative path, name-ordered."""
    found = []
    for tree in FILE_TREES:
        found.extend(
            {"name": f"{tree}/{a['name']}", "size": a["size"]}
            for a in list_artifact_tree(os.path.join(record_dir, tree))
        )
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
    stably sorted by timestamp — less what a rewind hides (see
    :mod:`vmn_exp.core.rewind`)."""
    entries = []
    for writer in sorted(logs_by_writer):
        entries.extend(logs_by_writer[writer])
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return drop_rewound(entries)


def merged_log(storage, app_name, verstr, logs_by_writer):
    """:func:`flatten_logs` of *logs_by_writer* with each writer's metric
    points back as ``metrics`` entries (plan 12 §5.5) — the log view."""
    logs = {w: list(entries or []) for w, entries in logs_by_writer.items()}
    metrics = SeriesReader.from_storage(storage, app_name, verstr, rewinds=())
    for writer, entries in metrics.entries_by_writer().items():
        logs.setdefault(writer, []).extend(entries)
    return flatten_logs(logs)


def _current_umask():
    """The process umask, read via the umask-swap idiom (there's no getter)."""
    mask = os.umask(0)
    os.umask(mask)
    return mask


def atomic_write(path, data):
    """Write *data* so readers see the old file or the new one, never half.

    ``mkstemp`` always creates its temp file at mode 0600, unlike a plain
    ``open()``. Chmod it to what ``open()`` would have produced under the
    process umask before the rename, so files stay readable by teammates on
    shared storage (e.g. an NFS-mounted experiment/snapshot dir).
    """
    directory, name = os.path.split(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.chmod(tmp, 0o666 & ~_current_umask())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
        path = os.path.join(directory, filename)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                data = f.read()
            patches[key] = data if binary else data.decode("utf-8")
    return patches
