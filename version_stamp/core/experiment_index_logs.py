#!/usr/bin/env python3
"""Keep one experiment's folded log current, reading as little as possible.

A record's log is the legacy ``log.yml`` (writer ``""``) plus, per writer,
``log.<writer>.jsonl`` and its segments ``log.<writer>@<seq>.jsonl``. JSONL
files only ever grow at the end and segments only ever get added after the
last one, so when that is all that changed only the new bytes are read and
folded. Anything else — a rewritten ``log.yml``, a shrunk or vanished file, a
file that grew *before* a later segment — refolds the record from scratch.

A backend whose reads merge several sources (``direct`` is None) cannot be
read per file; a change there refolds through its ``load_logs_by_writer``.
"""
import json

from version_stamp.core.experiment_fold import apply_entries, new_fold
from version_stamp.core.utils import yaml_safe_load

LEGACY_LOG = "log.yml"


def log_file_parts(name):
    """``("w", seq)`` for a JSONL log file name, ``("", -1)`` for ``log.yml``,
    None for anything else."""
    if name == LEGACY_LOG:
        return "", -1
    if not (name.startswith("log.") and name.endswith(".jsonl")):
        return None
    writer, _, seq = name[len("log.") : -len(".jsonl")].partition("@")
    return writer, int(seq) if seq.isdigit() else 0


def log_signatures(names):
    """The log files among ``{name: (size, mtime)}``, signatures as lists."""
    return {n: list(sig) for n, sig in names.items() if log_file_parts(n) is not None}


def _by_writer(names):
    groups = {}
    for name in names:
        writer, seq = log_file_parts(name)
        if seq >= 0:
            groups.setdefault(writer, []).append((seq, name))
    return {w: [n for _, n in sorted(items)] for w, items in groups.items()}


def _parse_complete(data):
    """``(entries, bytes consumed)`` — an unterminated line that is not yet
    valid JSON is left for the next read (its writer is mid-append)."""
    end = data.rfind(b"\n") + 1
    entries = []
    for line in data[:end].decode("utf-8", errors="replace").splitlines():
        entry = _parse_line(line)
        if entry is not None:
            entries.append(entry)
    tail = data[end:]
    if not tail.strip():
        return entries, len(data)
    entry = _parse_line(tail.decode("utf-8", errors="replace"))
    if entry is None:
        return entries, end
    entries.append(entry)
    return entries, len(data)


def _parse_line(line):
    line = line.strip()
    if not line:
        return None
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    return entry if isinstance(entry, dict) else None


def _appends_only(old, new):
    """Whether *new* is *old* with bytes appended / segments added at the end."""
    if old.get(LEGACY_LOG, {}).get("sig") != new.get(LEGACY_LOG):
        return False
    if any(name not in new for name in old):
        return False
    for names in _by_writer(new).values():
        grown = False
        for name in names:
            before = old.get(name)
            if before is None or before["sig"] != new[name]:
                if before is not None and new[name][0] <= before["sig"][0]:
                    return False  # rewritten or truncated in place
                grown = True
            elif grown:
                return False  # an earlier file changed under a later one
    return True


def _read_tail(fold, counts, direct, where, name, state):
    """Fold the bytes of *name* past ``state["consumed"]``; False if it vanished."""
    writer, _ = log_file_parts(name)
    data = direct.read_file_from(*where, name, state["consumed"])
    if data is None:
        return False
    entries, used = _parse_complete(data)
    apply_entries(fold, writer, counts.get(writer, 0), entries)
    counts[writer] = counts.get(writer, 0) + len(entries)
    state["consumed"] += used
    return True


def _refold_direct(record, storage, direct, where, sigs):
    fold, counts, logs = new_fold(), {}, {}
    if LEGACY_LOG in sigs:
        raw = storage.load_file(*where, LEGACY_LOG)
        legacy = yaml_safe_load(raw) if raw else None
        if isinstance(legacy, list):
            apply_entries(fold, "", 0, legacy)
        logs[LEGACY_LOG] = {"sig": sigs[LEGACY_LOG], "consumed": 0}
    for names in _by_writer(sigs).values():
        for name in names:
            logs[name] = {"sig": sigs[name], "consumed": 0}
            if not _read_tail(fold, counts, direct, where, name, logs[name]):
                return False
    record.update(fold=fold, counts=counts, logs=logs)
    return True


def _refold_merged(record, storage, where, sigs):
    fold = new_fold()
    loader = getattr(storage, "load_logs_by_writer", None)
    logs_by_writer = loader(*where) if loader else {"": storage.load_merged_log(*where)}
    for writer in sorted(logs_by_writer):
        apply_entries(fold, writer, 0, logs_by_writer[writer] or [])
    record.update(
        fold=fold,
        counts={},
        logs={n: {"sig": sig, "consumed": sig[0]} for n, sig in sigs.items()},
    )


def update_logs(record, storage, direct, app_name, key, sigs):
    """Bring *record*'s fold up to the log files *sigs*; True if it changed."""
    old = record["logs"]
    if {name: state["sig"] for name, state in old.items()} == sigs:
        return False
    where = (app_name, key)
    if direct is None:
        _refold_merged(record, storage, where, sigs)
        return True
    if _appends_only(old, sigs):
        fold, counts = record["fold"], record["counts"]
        ok = True
        for names in _by_writer(sigs).values():
            for name in names:
                state = old.get(name)
                if state is not None and state["sig"] == sigs[name]:
                    continue
                if state is None:
                    state = old[name] = {"sig": None, "consumed": 0}
                ok = ok and _read_tail(fold, counts, direct, where, name, state)
                state["sig"] = sigs[name]
        if ok:
            return True
    if not _refold_direct(record, storage, direct, where, sigs):
        _refold_merged(record, storage, where, sigs)
    return True
