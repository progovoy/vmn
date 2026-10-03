#!/usr/bin/env python3
"""Keep one experiment's folded log current, reading as little as possible.

A record's log is, per writer, ``log/<writer>.jsonl`` and its segments
``log/<writer>@<seq>.jsonl``. JSONL
files only ever grow at the end and segments only ever get added after the
last one, so when that is all that changed only the new bytes are read and
folded. Anything else — a shrunk or vanished file, a
file that grew *before* a later segment — refolds the record from scratch.

Local-first storage with a remote reads per file too: its listing takes each
writer's files from one copy (local or remote) and its ``read_file_from``
reads that same copy, so only new local bytes and new remote segments are read.
A file that vanishes mid-read refolds the record through the storage's
``load_logs_by_writer``.
"""
from vmn_exp.core.fold import apply_entries, fold_rewinds, needs_refold, new_fold
from vmn_exp.core.index_metrics import (
    metric_signatures,
    metric_state_sigs,
    refold_metrics,
    update_metrics,
)
from vmn_exp.core.jsonl_tail import read_complete_lines
from vmn_exp.core.logfiles import (
    group_log_names,
    log_writer_and_seq,
)


def log_signatures(names):
    """The log files a reader sees among ``{name: (size, mtime)}``, and every
    metric file (:mod:`index_metrics`), signatures as lists. Files a compacted object supersedes are left out: they vanish
    from the signatures the moment the merged object appears, which refolds
    the record instead of folding the merged copy on top of its parts."""
    visible = {n for group in group_log_names(names).values() for n in group}
    sigs = {n: list(sig) for n, sig in names.items() if n in visible}
    sigs.update(metric_signatures(names))
    return sigs


def _appends_only(old, new):
    """Whether *new* is *old* with bytes appended / segments added at the end."""
    if any(name not in new for name in old):
        return False
    for names in group_log_names(new).values():
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
    writer, _ = log_writer_and_seq(name)
    read = read_complete_lines(direct, *where, name, state["consumed"])
    if read is None:
        return False
    entries, used = read
    apply_entries(fold, writer, counts.get(writer, 0), entries)
    counts[writer] = counts.get(writer, 0) + len(entries)
    state["consumed"] += used
    return True


def _refold_direct(record, storage, direct, where, sigs, rewinds=()):
    fold, counts, logs = new_fold(rewinds), {}, {}
    for names in group_log_names(sigs).values():
        for name in names:
            logs[name] = {"sig": sigs[name], "consumed": 0}
            if not _read_tail(fold, counts, direct, where, name, logs[name]):
                return False
    record.update(fold=fold, counts=counts, logs=logs)
    return True


def _refold_merged(record, storage, where, sigs, rewinds=()):
    fold = new_fold(rewinds)
    logs_by_writer = storage.load_logs_by_writer(*where)
    for writer in sorted(logs_by_writer):
        apply_entries(fold, writer, 0, logs_by_writer[writer] or [])
    record.update(
        fold=fold,
        counts={},
        logs={n: {"sig": sig, "consumed": sig[0]} for n, sig in sigs.items()},
    )


def update_logs(record, storage, direct, app_name, key, sigs):
    """Bring *record*'s fold up to the log files *sigs*; True if it changed.

    A rewind the fold had not seen may hide entries it already folded, so the
    record is folded again knowing it (see :func:`~vmn_exp.core.fold.needs_refold`).
    """
    where = (app_name, key)
    sigs, metric_sigs = split_signatures(sigs)
    changed = _update_logs(record, storage, direct, where, sigs)
    grown = update_metrics(record, storage, where, metric_sigs)
    if grown is False:
        _refold(record, storage, direct, where, sigs)
    changed = changed or grown is not None
    if changed and needs_refold(record["fold"]):
        _refold(record, storage, direct, where, sigs, fold_rewinds(record["fold"]))
    return changed


def split_signatures(sigs):
    """``(log file signatures, metric file signatures)`` of *sigs*."""
    metric_sigs = metric_signatures(sigs)
    return {n: s for n, s in sigs.items() if n not in metric_sigs}, metric_sigs


def record_signatures(record):
    """The file signatures *record* was last folded at, logs and metrics."""
    sigs = {name: state["sig"] for name, state in record["logs"].items()}
    sigs.update(metric_state_sigs(record))
    return sigs


def _refold(record, storage, direct, where, sigs, rewinds=()):
    if not _refold_direct(record, storage, direct, where, sigs, rewinds):
        _refold_merged(record, storage, where, sigs, rewinds)
    refold_metrics(record, storage, where)


def _update_logs(record, storage, direct, where, sigs):
    old = record["logs"]
    if {name: state["sig"] for name, state in old.items()} == sigs:
        return False
    if _appends_only(old, sigs):
        fold, counts = record["fold"], record["counts"]
        ok = True
        for names in group_log_names(sigs).values():
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
    _refold(record, storage, direct, where, sigs)
    return True
