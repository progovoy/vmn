#!/usr/bin/env python3
"""Follower refresh for :class:`vmn_exp.core.index.ExperimentIndex`: catch up
with a shared :class:`~vmn_exp.core.cache_store.CacheStore` a leader saves into,
never touching storage (plan 11 §4.3)."""
from vmn_exp.core.cache_store import FULL_LOAD


def apply_delta(records, store, scope, generation):
    """Patch *records* (``{key: record}``, in place) with *store*'s changes
    since *generation*; ``(changed keys, removed keys, new generation)``.

    Past the tombstone horizon the delta is the full record set, so every key
    it lacks is removed."""
    changed, removed, new_gen = store.load_since(scope, generation)
    if removed is FULL_LOAD:
        removed = set(records) - set(changed)
    removed = {key for key in removed if key in records}
    for key in removed:
        del records[key]
    records.update(changed)
    return set(changed), removed, new_gen
