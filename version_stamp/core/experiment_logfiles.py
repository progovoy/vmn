#!/usr/bin/env python3
"""Names and lines of an experiment's log files — the one definition.

A record's log is the legacy ``log.yml`` plus, per writer, ``log.<writer>.jsonl``
and its segments ``log.<writer>@<seq>.jsonl``. Compaction merges a writer's
files up to segment N into ``log.<writer>@000000-<N>.jsonl``, which supersedes
every file it covers — so a reader that lists the merged object next to the
files it replaced (before they are deleted) still counts each entry once.

The storage backends write and read these; the experiment index folds them
incrementally. Both use this module, so a naming change can never make them
disagree about writers.
Pure: no I/O.
"""
import json

LEGACY_LOG_FILE = "log.yml"


def is_log_file(name):
    """Whether *name* is a per-writer JSONL log file or segment."""
    return name.startswith("log.") and name.endswith(".jsonl")


def _writer_and_span(name):
    """``(writer, (first seq, last seq))`` a log file covers."""
    stem = name[len("log.") : -len(".jsonl")]
    writer, _, seq = stem.partition("@")
    first, _, last = seq.partition("-")
    if first.isdigit() and last.isdigit():
        return writer, (int(first), int(last))
    n = int(seq) if seq.isdigit() else 0
    return writer, (n, n)


def log_writer_and_seq(name):
    """``log.w.jsonl`` → ``("w", 0)``; segment ``log.w@000003.jsonl`` → ``("w", 3)``;
    a compacted ``log.w@000000-000005.jsonl`` → ``("w", 5)``, its last seq."""
    writer, (_, last) = _writer_and_span(name)
    return writer, last


def log_object_name(writer, seq=0):
    return f"log.{writer}.jsonl" if not seq else f"log.{writer}@{seq:06d}.jsonl"


def compacted_log_name(writer, last_seq):
    """The object merging *writer*'s files up to segment *last_seq*."""
    return f"log.{writer}@{0:06d}-{last_seq:06d}.jsonl"


def _visible(spans):
    """*spans* ``[((first, last), name)]`` minus the files a merged one covers."""
    merged = max((s for s in spans if s[0][0] < s[0][1]), default=None)
    if merged is None:
        return sorted(spans)
    (first, last), _ = merged
    kept = [s for s in spans if s is merged or not first <= s[0][0] <= last]
    return sorted(kept, key=lambda s: s[0][1])


def group_log_names(names):
    """``{writer: [names in seq order]}`` for the log files among *names*,
    leaving out the files a compacted object supersedes."""
    groups = {}
    for name in names:
        if is_log_file(name):
            writer, span = _writer_and_span(name)
            groups.setdefault(writer, []).append((span, name))
    return {w: [n for _, n in _visible(spans)] for w, spans in groups.items()}


# json.loads minus its per-call Python layers: the C scanner at offset 0 of a
# stripped line is exactly json.loads when it consumes the whole line.
_scan = json.JSONDecoder().scan_once


def parse_json_line(line):
    """One log entry from a JSONL line, or None for a blank/corrupt/non-object line."""
    line = line.strip()
    if not line:
        return None
    try:
        entry, end = _scan(line, 0)
    except (StopIteration, ValueError):
        return None
    return entry if end == len(line) and isinstance(entry, dict) else None


def parse_jsonl(text, writer):
    """The entries of a JSONL log, each tagged with its ``_writer``."""
    entries = []
    for line in text.splitlines():
        entry = parse_json_line(line)
        if entry is not None:
            entry["_writer"] = writer
            entries.append(entry)
    return entries
