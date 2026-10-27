#!/usr/bin/env python3
"""Keep one experiment's folded log current, reading as little as possible.

A record's log is, per writer, ``log/<writer>.jsonl`` and its segments
``log/<writer>@<seq>.jsonl``. JSONL
files only ever grow at the end and segments only ever get added after the
last one, so when that is all that changed only the new bytes are read and
folded. Anything else — a shrunk or vanished file, a
file that grew *before* a later segment, one rewritten into a bigger file or
read from another copy (its signature's
:func:`~vmn_exp.core.logfiles.append_identity` moved) — refolds the record
from scratch.

Local-first storage with a remote reads per file too: its listing takes each
writer's files from one copy (local or remote) and its ``read_file_from``
reads that same copy, so only new local bytes and new remote segments are read.
A file that vanishes mid-read refolds the record through the storage's
``load_logs_by_writer`` (which lists it afresh), without first reading the
stale listing's other files.
"""
from vmn_exp.core.fold import apply_entries, fold_rewinds, needs_refold, new_fold
from vmn_exp.core.index_metrics import (
    metric_signatures,
    metric_state_sigs,
    refold_metrics,
    update_metrics,
)
from vmn_exp.core.jsonl_tail import complete_lines
from vmn_exp.core.logfiles import appended, group_log_names, log_writer_and_seq
from vmn_exp.storage.s3_base import parallel_map

# Grown files past which one is read alone first (a stale listing's rest):
# a vanish then wastes one read, while a live run's few new files cost no
# extra round trip.
PROBE_OVER = 4


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
                if before is not None and not appended(before["sig"], new[name]):
                    return False  # rewritten, truncated or another copy
                grown = True
            elif grown:
                return False  # an earlier file changed under a later one
    return True


def _read_tails(fold, counts, direct, where, items, probe=False):
    """Fold each ``(name, state)`` of *items*' bytes past ``state["consumed"]``,
    in order, their reads in flight together; False if one vanished. With
    *probe* the first is read alone first: files listed long ago (a cold
    load's rest) may have been merged since, and then one read misses, not
    every one of them."""
    read = lambda item: direct.read_file_from(*where, item[0], item[1]["consumed"])  # noqa: E731
    if probe and items:
        first = read(items[0])
        if first is None:
            return False
        datas = [first] + parallel_map(read, items[1:])
    else:
        datas = parallel_map(read, items)
    for (name, state), data in zip(items, datas):
        if data is None:
            return False
        writer, _ = log_writer_and_seq(name)
        entries, used = complete_lines(data)
        apply_entries(fold, writer, counts.get(writer, 0), entries)
        counts[writer] = counts.get(writer, 0) + len(entries)
        state["consumed"] += used
    return True


def _refold_direct(record, storage, direct, where, sigs, rewinds=()):
    fold, counts, logs = new_fold(rewinds), {}, {}
    for names in group_log_names(sigs).values():
        for name in names:
            logs[name] = {"sig": sigs[name], "consumed": 0}
    if not _read_tails(fold, counts, direct, where, list(logs.items())):
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


def _refold_relisted(record, storage, where, sigs):
    """Refold *record* after a file *sigs* list vanished: they are stale, so
    reading them again would miss again; the storage lists the record afresh."""
    _refold_merged(record, storage, where, sigs)
    if needs_refold(record["fold"]):
        _refold_merged(record, storage, where, sigs, fold_rewinds(record["fold"]))
    refold_metrics(record, storage, where)


def _update_logs(record, storage, direct, where, sigs):
    old = record["logs"]
    if {name: state["sig"] for name, state in old.items()} == sigs:
        return False
    if _appends_only(old, sigs):
        grown = []
        for names in group_log_names(sigs).values():
            for name in names:
                state = old.get(name)
                if state is not None and state["sig"] == sigs[name]:
                    continue
                if state is None:
                    state = old[name] = {"sig": None, "consumed": 0}
                grown.append((name, state))
                state["sig"] = sigs[name]
        probe = len(grown) > PROBE_OVER
        if _read_tails(record["fold"], record["counts"], direct, where, grown, probe=probe):
            return True
        _refold_relisted(record, storage, where, sigs)
        return True
    _refold(record, storage, direct, where, sigs)
    return True
