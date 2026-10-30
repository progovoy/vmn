#!/usr/bin/env python3
"""``--query`` selection logic for ``vmn-exp prune``.

:func:`query_candidates` loads the full indexed rows (status, metrics, tags, and
the snapshot fields: intents, similar-runs documents)
so the query language sees the same fields as ``vmn-exp list --query``.
:func:`print_preview` renders the dry-run summary, capped at 20 entries.
"""
from vmn_exp.core.index_list import snapshot_listing
from vmn_exp.core.query import compile_query

_PREVIEW_CAP = 20


def query_candidates(storage, app_name, metas, query_text, schema=None):
    """Return the subset of *metas* whose full rows match *query_text*;
    *schema* (the app's metrics schema) sets which value ``metrics.x`` is.

    Raises :class:`~version_stamp.core.experiment_query.QueryError` for an
    empty or syntactically invalid query.  Callers must catch it.
    """
    compile_query(query_text)  # raises QueryError on bad input, an empty one too
    rows, _, _ = snapshot_listing(storage, app_name, query_text, schema)
    matching = {row["verstr"] for row in rows}
    return [m for m in metas if m["verstr"] in matching]


def print_preview(header, verstrs, cap=_PREVIEW_CAP):
    """Print the dry-run *header* and *verstrs*, showing at most *cap* of them.

    When more than *cap* entries are present, the last line reports how many
    were omitted: ``... and N more``.
    """
    shown = verstrs[:cap]
    extra = len(verstrs) - len(shown)
    print(header)
    for verstr in shown:
        print(f"  {verstr}")
    if extra > 0:
        print(f"  ... and {extra} more")
