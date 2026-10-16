#!/usr/bin/env python3
"""An index's listing baselines, persisted beside its records (plan 25 §2).

A refresh judges records against what the previous listings saw: each
record's name signature and file fingerprint (the
:class:`~vmn_exp.core.index_listing.ListingWatch`) and the sweep's clock and
sets (:class:`~vmn_exp.core.index_sweep_state.SweepState`). Saved here after
each refresh, they let a new process list record names once and re-read only
the records whose signature moved, the live ones and the recently changed
ones, instead of starting with a full listing of every record's files.

They live in the cache store's key-value table: the per-record part in shards
of at most ``SHARD_SIZE`` records (a refresh rewrites only the shards whose
records moved), then a head naming the shard count, written last. Shards of
another count, or a missing one, read as no baseline: the next listing is a
full one.

Ordering keeps a baseline from vouching for records the store lacks: it is
read before the records and written after them, and not at all while a failed
save left records unsaved. A baseline older than the records only costs extra
re-reads.
"""
import zlib

from vmn_exp.core import index_sweep

FORMAT = "listing-baseline-1"
SHARD_SIZE = 1000
MAX_SHARDS = 256


def _sig(value):
    """A sig back from JSON: listings sign records with flat tuples."""
    return tuple(value) if isinstance(value, list) else value


def _tag(count):
    return f"{FORMAT}/{count}"


def _shard_count(size):
    count = 1
    while count < MAX_SHARDS and size > count * SHARD_SIZE:
        count *= 2
    return count


def _shard_of(key, count):
    return zlib.crc32(key.encode()) % count


class ListingBaseline:
    """The baseline of *store*'s *app_name* index."""

    def __init__(self, store, app_name):
        self._store, self._scope = store, f"listing:{app_name}"
        self._shards = None  # [{key: [sig, fingerprint]}] as last persisted
        self._head = None  # the head as last persisted

    def load(self, sweep, now):
        """Restore *sweep* from the persisted baseline, if there is one."""
        head = self._store.kv_get(self._scope, FORMAT)
        if not head:
            return
        count, shards = head["shards"], []
        for i in range(count):
            shard = self._store.kv_get(f"{self._scope}:{i}", _tag(count))
            if shard is None:
                return
            shards.append({key: [_sig(sig), fp] for key, (sig, fp) in shard.items()})
        names = {key: e[0] for shard in shards for key, e in shard.items()}
        prints = {key: e[1] for shard in shards for key, e in shard.items() if e[1] is not None}
        sweep.watch.restore(names, prints)
        sweep.restore_state(head["sweep"], names, now, index_sweep._wall())
        self._shards, self._head = shards, head

    def save(self, sweep, now):
        """Persist *sweep*'s baseline: the shards whose records moved, then the head."""
        names, prints, moved = sweep.watch.baseline()
        count = _shard_count(len(names))
        rewrite = moved is None or self._shards is None or len(self._shards) != count
        if rewrite:
            self._shards, moved = [{} for _ in range(count)], names.keys()
        dirty = self._apply(moved, names, prints, count)
        for i in range(count) if rewrite else sorted(dirty):
            self._store.kv_put(f"{self._scope}:{i}", _tag(count), self._shards[i])
        head = {"shards": count, "sweep": sweep.export_state(now, index_sweep._wall())}
        if dirty or rewrite or head != self._head:  # an idle refresh writes nothing
            self._store.kv_put(self._scope, FORMAT, head)
            self._head = head

    def _apply(self, moved, names, prints, count):
        """Put the *moved* keys' entries in their shards; the shards changed."""
        dirty = set()
        for key in moved:
            at = _shard_of(key, count)
            entry = [names[key], prints.get(key)] if key in names else None
            if self._shards[at].get(key) == entry:
                continue
            if entry is None:
                del self._shards[at][key]
            else:
                self._shards[at][key] = entry
            dirty.add(at)
        return dirty
