#!/usr/bin/env python3
"""``vmn-exp list --query`` matching nothing: the board's "did you mean
tags.<field>?" hints (:mod:`vmn_exp.core.query_hints`), on stderr."""
import sys

from vmn_exp.core.query_hints import hints, row_equalities


def print_query_hints(query, rows_of):
    """Hint at *query*'s row-field equalities from the rows *rows_of()*
    lists — asked only when it has one to hint at."""
    if not row_equalities(query):
        return
    rows = rows_of()

    def carries(prefix, field, value):
        return any((row.get(prefix) or {}).get(field) == value for row in rows)

    for line in hints((query,), carries):
        print(line, file=sys.stderr)
