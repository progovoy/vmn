#!/usr/bin/env python3
"""What moved among an app's records, at no stat per record (plan 25 §1:
a refresh after 100 changed runs within 0.2 s at 100k).

A local store's ``list_record_names`` signs each record with its
directory's ``(mtime, inode)`` — a stat per record, ~0.3 s at 100k, and
listing the names alone still costs ~0.07 s. But a journaled local store
(:mod:`vmn_exp.storage.journal`: every write that changes what a reader
sees — a claim and a delete included — puts an entry naming its record)
already says which records changed. So :func:`journal_moves` answers what
moved since the previous listing from the records the journal named since
it, minus a skew window (for writers whose clocks lag or whose entry landed
late): one whose directory is gone is gone, any other is signed with its
newest journal key — a value it never had, so the sweep lists its files
again (and re-reads it only if they moved).

It answers None — the caller signs every record — when it cannot vouch or
need not: fewer than :data:`MIN_RECORDS` records, no previous listing
time, a store with a writer that does not journal into it (a local root
fronting a remote store), or more journal entries in the window than
:data:`MAX_ENTRIES`. What no journal entry names (a hand edit or delete, a
writer bypassing the store) shows up by the next full sweep, as for a change
no signature shows.
"""
from vmn_exp.core.journal_reader import JournalReader
from vmn_exp.storage.areas import app_key
from vmn_exp.storage.journal_sinks import journal_sinks

SKEW_SEC = 300
MAX_ENTRIES = 20_000
# Below this many records signing them all costs a few ms: the journal is
# not worth what it cannot see (a write that bypasses the store).
MIN_RECORDS = 5000


def journal_source(storage):
    """``(list_fn, area, local store)`` of the journal every writer of
    *storage*'s local records journals into, or None."""
    local = getattr(storage, "_local", storage)
    if getattr(storage, "_remote", None) is not None or not hasattr(local, "local_record_dir"):
        return None
    sinks = journal_sinks(local)
    return (sinks[0].list, local.area, local) if sinks else None


def journal_moves(storage, app_name, before, since, now):
    """``(changed {name: sig}, gone names)`` of *app_name*'s records since
    the listing at wall time *since* that found *before* (``{name: sig}``):
    the records the journal named since, signed with their newest journal
    key, and those of them whose directory is gone; None when it cannot tell
    (see the module)."""
    wanted = since is not None and len(before) >= MIN_RECORDS
    source = journal_source(storage) if wanted else None
    if source is None:
        return None
    list_fn, area, local = source
    named = _named_since(list_fn, area, app_key(app_name), since, now)
    if named is None:
        return None
    changed, gone = {}, set()
    for name, token in named.items():
        if not _has_dir(local, app_name, name):
            if name in before:
                gone.add(name)
        elif before.get(name) != token:
            changed[name] = token
    return changed, gone


def _has_dir(local, app_name, name):
    try:
        return local.local_record_dir(app_name, name) is not None
    except ValueError:  # not a record name: no record
        return False


def _named_since(list_fn, area, key, since, now):
    """``{record name: its newest journal key}`` of the entries of *area*/
    *key* from *since* (minus the skew window) to *now*; None past the cap."""
    reader = JournalReader(list_fn, lambda: now, skew_window_sec=SKEW_SEC,
                           max_per_scope=MAX_ENTRIES, last_seen_ms=int(since * 1000))
    result = reader.tick()
    if (area, key) in result.overflow:
        return None
    return {entry.name: f"journal:{entry.unix_ms}:{entry.writer_id}:{entry.seq}"
            for entry in result.entries.get((area, key), ())}
