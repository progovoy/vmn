#!/usr/bin/env python3
"""Records an upgrade left to read again from storage.

An upgrade in place of older records (:mod:`vmn_exp.core.index_store_upgrade`)
deletes those its version's predicate picks, with their run states, and
lists their keys in the cache store's key-value table under
``reread:<app>`` (fingerprint :data:`FINGERPRINT`), joining those an
earlier upgrade listed and no load has read yet. Deleted, such a record
is no tombstone: a follower keeps it until its re-read is saved. An index
loading its records hints those the list names and the records lack, so the
next refresh lists and loads them like a journal-announced run — whether it
resumes from a journal mark (which never lists an unhinted record) or from a
listing baseline. The list shrinks to what is still missing at each load, so
a refresh that died before saving a re-read hints it again.
"""
from vmn_exp.core.index_store_kv import read_payload

SCOPE = "reread:"
FINGERPRINT = "reread-1"


def puts(conn, keys):
    """The kv puts listing *keys* (``(app, key)`` pairs) to read again,
    beside those *conn* lists already (an earlier upgrade's, not yet read)."""
    return [(SCOPE + app, FINGERPRINT,
             sorted(names.union(read_payload(conn, SCOPE + app, FINGERPRINT) or ())))
            for app, names in by_app(keys).items()]


def by_app(keys):
    """``{app: {key}}`` of ``(app, key)`` pairs."""
    grouped = {}
    for app, key in keys:
        grouped.setdefault(app, set()).add(key)
    return grouped


def hint_unloaded(store, app_name, records, hint):
    """*hint* each key listed to read again that *records* lacks."""
    listed = store.kv_get(SCOPE + app_name, FINGERPRINT)
    if not listed:
        return
    missing = [key for key in listed if key not in records]
    for key in missing:
        hint(key)
    if len(missing) < len(listed):
        store.kv_put(SCOPE + app_name, FINGERPRINT, missing)
