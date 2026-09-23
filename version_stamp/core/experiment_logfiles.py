#!/usr/bin/env python3
"""Names and lines of an experiment's log files — the one definition.

A record's log is the legacy ``log.yml`` plus, per writer, ``log.<writer>.jsonl``
and its segments ``log.<writer>@<seq>.jsonl``. The storage backends write and
read these; the experiment index folds them incrementally. Both use this
module, so a naming change can never make them disagree about writers.
Pure: no I/O.
"""
import json

LEGACY_LOG_FILE = "log.yml"


def is_log_file(name):
    """Whether *name* is a per-writer JSONL log file or segment."""
    return name.startswith("log.") and name.endswith(".jsonl")


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


def parse_json_line(line):
    """One log entry from a JSONL line, or None for a blank/corrupt/non-object line."""
    line = line.strip()
    if not line:
        return None
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    return entry if isinstance(entry, dict) else None


def parse_jsonl(text, writer):
    """The entries of a JSONL log, each tagged with its ``_writer``."""
    entries = []
    for line in text.splitlines():
        entry = parse_json_line(line)
        if entry is not None:
            entry["_writer"] = writer
            entries.append(entry)
    return entries
