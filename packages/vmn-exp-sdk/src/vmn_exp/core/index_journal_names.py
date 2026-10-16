#!/usr/bin/env python3
"""Record names with signatures that cost no stat per record (plan 25 §1:
a refresh after 100 changed runs within 0.2 s at 100k).

A local store's ``list_record_names`` signs each record with its
directory's ``(mtime, inode)`` — a stat per record, ~0.3 s at 100k. But a
journaled local store (:mod:`vmn_exp.storage.journal`: every write that
changes what a reader sees puts an entry naming its record) already says
which records changed. So :func:`journal_names` takes the names from one
directory listing (no stat) and the signatures from the previous listing,
except for the records the journal named since it — minus a skew window, for
writers whose clocks lag or whose entry landed late — which are signed with
their newest journal key: a value they never had, so the sweep lists their
files again (and re-reads them only if their files moved).

It answers None — the caller signs every record — when it cannot vouch or
need not: fewer than :data:`MIN_RECORDS` records, no previous listing
time, a store with a writer that does not journal into it (a local root
fronting a remote store), or more journal entries in the window than
:data:`MAX_ENTRIES`. What no journal entry names (a hand edit,
a writer bypassing the store) shows up by the next full sweep, as for a
change no signature shows.
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
    """``(list_fn, area)`` of the journal every writer of *storage*'s local
    records journals into, or None."""
    local = getattr(storage, "_local", storage)
    if getattr(storage, "_remote", None) is not None or not hasattr(local, "list_record_keys"):
        return None
    sinks = journal_sinks(local)
    return (sinks[0].list, local.area) if sinks else None


def journal_names(storage, app_name, before, since, now):
    """``{name: sig}`` for every record name of *app_name*: *before*'s sig
    (``{name: sig}`` of the listing at wall time *since*), or the newest
    journal key naming the record since then; None when it cannot tell (see
    the module)."""
    wanted = since is not None and len(before) >= MIN_RECORDS
    source = journal_source(storage) if wanted else None
    if source is None:
        return None
    named = _named_since(*source, app_key(app_name), since, now)
    if named is None:
        return None
    return {name: named.get(name, before.get(name))
            for name in storage.list_record_keys(app_name)}


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
