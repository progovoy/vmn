#!/usr/bin/env python3
"""``vmn-exp list --query`` matching nothing: the board's "did you mean
tags.<field>?" hints (:mod:`vmn_exp.ui.query_hints`), on stderr."""
import sys

import vmn_exp.core.index_list as index_list
from vmn_exp.core.log import filter_archived


def print_query_hints(storage, app_name, query, archived):
    """Read every run only when *query* has a row-field equality to hint at."""
    from vmn_exp.ui.leaderboard_facets import FacetCounts
    from vmn_exp.ui.query_hints import hints, row_equalities

    if not row_equalities(query):
        return
    rows = filter_archived(index_list.snapshot_listing(storage, app_name)[0], archived)
    for line in hints((query,), FacetCounts.of(rows)):
        print(line, file=sys.stderr)
