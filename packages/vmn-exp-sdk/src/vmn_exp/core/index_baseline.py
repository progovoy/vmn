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
full one. A shard holds its records as columns (names, then signatures and
fingerprints packed as machine integers when they are ints), not a JSON
entry per record: a cold refresh of a 100k store decodes every shard.

Ordering keeps a baseline from vouching for records the store lacks: it is
read before the records and written after them (in the same transaction
when the store can, :meth:`ListingBaseline.puts`), and not at all while a
failed save left records unsaved. A baseline older than the records only costs extra
re-reads.
"""
import base64
import sys
import zlib
from array import array

# Packed integers are this machine's byte order.
FORMAT = f"listing-baseline-3-{sys.byteorder}"
# Small shards: a refresh that moved a few records spread over the app
# rewrites a few hundred entries, not most of them.
SHARD_SIZE = 100
MAX_SHARDS = 4096


def _sig(value):
    """A sig back from JSON: listings sign records with flat tuples."""
    return tuple(value) if isinstance(value, list) else value


def _column(values):
    """*values* as a string of packed 64-bit integers (its typecode first)
    when they all are ones, else as they are."""
    for code in "qQ":
        try:
            return code + base64.b64encode(array(code, values).tobytes()).decode()
        except (OverflowError, TypeError):
            pass
    return values


def _values(column):
    if isinstance(column, str):
        return array(column[0], base64.b64decode(column[1:])).tolist()
    return column


def _encode(keys, names, prints):
    """The shard of *keys*: the printed first, so a fingerprint column lines up with them."""
    keys = sorted(keys, key=lambda key: key not in prints)
    sigs = [names[key] for key in keys]
    columns = _sig_columns(sigs)
    return {"keys": keys, **({"sig_columns": columns} if columns else {"sigs": sigs}),
            "prints": _column([prints[key] for key in keys if key in prints])}


def _sig_columns(sigs):
    """Tuples of one length of ints as a packed column per position, else None."""
    if not all(isinstance(sig, tuple) and sig and len(sig) == len(sigs[0]) for sig in sigs):
        return None
    columns = [_column(list(values)) for values in zip(*sigs)]
    return columns if all(isinstance(column, str) for column in columns) else None


def _decode(shard):
    """``(keys, (key, sig) pairs, (key, fingerprint) pairs)`` of a stored shard."""
    keys = shard["keys"]
    columns = shard.get("sig_columns")
    sigs = zip(*map(_values, columns)) if columns else map(_sig, shard["sigs"])
    return keys, zip(keys, sigs), zip(keys, _values(shard["prints"]))


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
        self._shards = None  # each shard's keys as last persisted: a list until a save moves them
        self._head = None  # the head as last persisted

    def load(self, sweep, now):
        """Restore *sweep* from the persisted baseline, if there is one."""
        head = self._store.kv_get(self._scope, FORMAT)
        if not head:
            return
        count, shards, names, prints = head["shards"], [], {}, {}
        for shard in self._shards_stored(count):
            if shard is None:
                return
            keys, sigs, printed = _decode(shard)
            names.update(sigs)
            prints.update(printed)
            shards.append(keys)
        sweep.watch.restore(names, prints)
        sweep.restore_state(head["sweep"], names, now, sweep.wall())
        self._shards, self._head = shards, head

    def _shards_stored(self, count):
        scopes = [f"{self._scope}:{i}" for i in range(count)]
        get_many = getattr(self._store, "kv_get_many", None)
        if get_many is not None:
            found = get_many(scopes, _tag(count))
            return [found.get(scope) for scope in scopes]
        return [self._store.kv_get(scope, _tag(count)) for scope in scopes]

    def save(self, sweep, now):
        """Persist *sweep*'s baseline: the shards whose records moved, then the head."""
        puts = self.puts(sweep, now)
        put_many = getattr(self._store, "kv_put_many", None)
        if put_many is not None:
            put_many(puts)
        else:
            for put in puts:
                self._store.kv_put(*put)

    def forget(self):
        """The puts last handed out were not persisted: rewrite it all next time."""
        self._shards = self._head = None

    def puts(self, sweep, now):
        """The ``(scope, fingerprint, payload)`` writes that persist *sweep*'s
        baseline (the head last), as :meth:`save` writes them."""
        names, prints, moved = sweep.watch.baseline()
        count = _shard_count(len(names))
        rewrite = moved is None or self._shards is None or len(self._shards) != count
        if rewrite:
            self._shards, moved = [set() for _ in range(count)], names.keys()
        dirty = self._apply(moved, names, count)
        puts = [(f"{self._scope}:{i}", _tag(count), _encode(self._shards[i], names, prints))
                for i in (range(count) if rewrite else sorted(dirty))]
        head = {"shards": count, "sweep": sweep.export_state(now, sweep.wall())}
        if dirty or rewrite or head != self._head:  # an idle refresh writes nothing
            puts.append((self._scope, FORMAT, head))  # last: it vouches for the shards
            self._head = head
        return puts

    def _apply(self, moved, names, count):
        """File the *moved* keys in their shards; the shards they are in or left."""
        dirty = set()
        for key in moved:
            at = _shard_of(key, count)
            keys = self._shards[at]
            if not isinstance(keys, set):
                keys = self._shards[at] = set(keys)
            if key in names:
                keys.add(key)
            elif key in keys:
                keys.remove(key)
            else:
                continue
            dirty.add(at)
        return dirty
