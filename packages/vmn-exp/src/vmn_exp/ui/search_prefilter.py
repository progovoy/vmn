#!/usr/bin/env python3
"""Candidate rows for a query from the search index (plan 23 S8).

A ``field ~ "text"`` clause on an indexed field holds only for the slots
whose packed text of that field holds the text, so :func:`candidates` reads
them off the index, intersects them across ``and`` (ignoring clauses it
cannot answer) and unions them across ``or`` (only when every branch can be
answered). The result is a superset: the query is still evaluated on each
candidate, so what matches never changes — only how many rows are looked at.
"""
from vmn_exp.ui.search_index import FIELDS, needle_of

# Row fields the index holds as they are (params and intent are no row
# field), and dicts whose every value it holds.
_ROW_FIELDS = frozenset(FIELDS) - {"params", "intent"}
_DICT_FIELDS = frozenset(("tags", "params"))


def _field(path):
    """The index field answering ``~`` on the query *path*, or None."""
    if len(path) == 1 and path[0] in _ROW_FIELDS:
        return path[0]
    if len(path) == 2 and path[0] in _DICT_FIELDS:
        return path[0]
    return None


def candidates(node, index):
    """The set of slots that may satisfy the query AST *node* (see
    :func:`~vmn_exp.core.query.parse_query`), or None for every slot."""
    kind = node[0]
    if kind == "and":
        found = [c for c in (candidates(term, index) for term in node[1]) if c is not None]
        return set.intersection(*found) if found else None
    if kind == "or":
        found = [candidates(term, index) for term in node[1]]
        return None if any(c is None for c in found) else set().union(*found)
    if kind != "cmp" or node[2] != "~" or node[1][0] != "path":
        return None
    field, needle = _field(node[1][1]), needle_of(node[3])
    if field is None or needle is None:
        return None
    return index.slots(needle, [field])
