#!/usr/bin/env python3
"""``--query`` selection logic for ``vmn exp prune``.

:func:`query_candidates` loads the full indexed rows (status, metrics, tags)
so the query language sees the same fields as ``vmn exp list --query``.
:func:`print_preview` renders the dry-run summary, capped at 20 entries.
"""
from vmn_exp.core.index import indexed_status_rows
from vmn_exp.core.query import compile_query
from vmn_exp.core.tree import annotate_rows

_PREVIEW_CAP = 20


def query_candidates(storage, app_name, metas, query_text):
    """Return the subset of *metas* whose full rows match *query_text*.

    Raises :class:`~version_stamp.core.experiment_query.QueryError` for an
    empty or syntactically invalid query.  Callers must catch it.
    """
    predicate = compile_query(query_text)  # raises QueryError on bad input
    rows, run_states, observed = indexed_status_rows(storage, app_name)
    tree_rows = annotate_rows(rows, run_states, observed)
    matching = {row["verstr"] for row in tree_rows if predicate(row)}
    return [m for m in metas if m["verstr"] in matching]


def print_preview(to_delete, cap=_PREVIEW_CAP):
    """Print the dry-run summary for *to_delete*, showing at most *cap* entries.

    When more than *cap* entries are present, the last line reports how many
    were omitted: ``... and N more``.
    """
    shown = to_delete[:cap]
    extra = len(to_delete) - len(shown)
    print(f"Would delete {len(to_delete)} experiments:")
    for meta in shown:
        print(f"  {meta['verstr']}")
    if extra > 0:
        print(f"  ... and {extra} more")
