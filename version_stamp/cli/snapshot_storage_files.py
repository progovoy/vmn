#!/usr/bin/env python3
"""File-level helpers shared by the snapshot storage backends: record file
names, log object naming, JSONL parsing, atomic writes and patch files."""
import json
import os
import shutil
import tempfile

METADATA_FILE = "metadata.yml"
LEGACY_LOG_FILE = "log.yml"
# (patches key, file name, binary?)
PATCH_FILES = (
    ("working_tree", "working_tree.patch", False),
    ("local_commits", "local_commits.patch", False),
    ("untracked_files", "untracked_files.tar.gz", True),
)
# Rewritten while a run lives, so a copy fetched from a remote is stale at once.
VOLATILE_FILES = ("run_state.yml",)


def safe_verstr(verstr):
    return verstr.replace("+", "_plus_")


def unsafe_verstr(name):
    return name.replace("_plus_", "+")


def safe_dep_name(dep_path):
    return dep_path.replace(os.sep, "_").replace("/", "_")


def is_log_file(name):
    return name.startswith("log.") and name.endswith(".jsonl")


def is_volatile_file(name):
    return name in VOLATILE_FILES or is_log_file(name)


def log_writer_and_seq(name):
    """``log.w.jsonl`` → ``("w", 0)``; segment ``log.w@000003.jsonl`` → ``("w", 3)``."""
    stem = name[len("log.") : -len(".jsonl")]
    writer, _, seq = stem.partition("@")
    return writer, int(seq) if seq.isdigit() else 0


def log_object_name(writer, seq=0):
    return f"log.{writer}.jsonl" if not seq else f"log.{writer}@{seq:06d}.jsonl"


def group_log_names(names):
    """``{writer: [names in seq order]}`` for the log files among *names*."""
    groups = {}
    for name in names:
        if is_log_file(name):
            writer, seq = log_writer_and_seq(name)
            groups.setdefault(writer, []).append((seq, name))
    return {w: [n for _, n in sorted(items)] for w, items in groups.items()}


def valid_artifact_name(name):
    return bool(name) and name not in (".", "..") and not any(
        sep in name for sep in ("/", "\\", os.sep)
    )


def parse_jsonl(text, writer):
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        entry["_writer"] = writer
        entries.append(entry)
    return entries


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


def write_patches_to_dir(directory, patches, link_from=()):
    """Write the patch files *patches* carries and drop the ones it lacks.

    A byte-identical file in one of the *link_from* directories is hard-linked
    rather than written again, so runs of the same code share their patches.
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
                for src in link_from
                if _same_bytes(os.path.join(src, filename), data)
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
