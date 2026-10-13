#!/usr/bin/env python3
"""⌘K "go to run" over a :class:`~vmn_exp.ui.search_index.SearchIndex`
(plan 23 S8): ranked matches, each with its job.

Tiers, each newest first: the run whose ``@N`` (or bare ``N``) is the text,
then verstr prefixes, name prefixes, then a hit in any field (reported as
the first such field in :data:`~vmn_exp.ui.search_index.FIELDS` order).
Archived runs are left out unless asked for.
"""
import re
from itertools import islice

from vmn_exp.core.status import derive_status
from vmn_exp.ui.search_index import FIELDS, SEP, needle_of

_AT_N = re.compile(r"@?(\d+)")


def ranked(index, text, limit, archived=False):
    """``[(slot, matched field)]``, at most *limit*."""
    needle = needle_of((text or "").strip())
    if needle is None or limit < 1:
        return []
    rows, found, seen = index.snapshot.rows, [], set()

    def shown(slot):
        return slot not in seen and (archived or not rows[slot].get("archived"))

    def take(slots, field):
        for slot in islice(filter(shown, slots), limit - len(found)):
            seen.add(slot)
            found.append((slot, field))
        return len(found) >= limit

    if (take(_at_n(rows, needle), "idx")
            or take(index.newest(SEP + needle, "verstr"), "verstr")
            or take(index.newest(SEP + needle, "name"), "name")):
        return found
    need, hits = limit - len(found), {}
    for field in FIELDS:  # each field's newest *need* hold the overall newest *need*
        for slot in islice(filter(shown, index.newest(needle, field)), need):
            hits.setdefault(slot, field)
    found.extend(sorted(hits.items(), reverse=True)[:need])
    return found


def _at_n(rows, needle):
    match = _AT_N.fullmatch(needle)
    if not match:
        return []
    n = int(match.group(1))
    if not 0 < n <= len(rows):  # idx is the 1-based storage index
        return []
    if rows[n - 1].get("idx") == n:
        return [n - 1]
    return [i for i, row in enumerate(rows) if row.get("idx") == n]


def _root(snapshot, verstr):
    """The top-level ancestor of *verstr* present in *snapshot*, or None."""
    edges, root, seen = snapshot.edges, None, {verstr}
    parent = edges.get(verstr)
    while parent in edges and parent not in seen:
        root = parent
        seen.add(parent)
        parent = edges.get(parent)
    return root


def results(snapshot, hits):
    """The route's payload rows for *hits* ``[(slot, field)]``."""
    out = []
    for slot, field in hits:
        row = snapshot.rows[slot]
        verstr = row["verstr"]
        root = _root(snapshot, verstr)
        out.append({
            "verstr": verstr, "idx": row.get("idx"), "name": row.get("name"),
            "status": derive_status(snapshot.run_states.get(verstr),
                                    observed_at=snapshot.run_state_observed_at.get(verstr)),
            "root": root, "root_name": root and snapshot.row(root).get("name"),
            "match": field,
        })
    return out
