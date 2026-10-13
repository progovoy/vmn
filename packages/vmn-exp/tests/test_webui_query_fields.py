"""The web UI's query field list mirrors the query language's ROW_FIELDS.

The leaderboard reads typed text that compares a word outside that list as a
text search (plan 20 D10), so a missing field would make a valid query
search text instead.
"""

import os
import re

from vmn_exp.core.query import ROW_FIELDS

WEBUI = os.path.join(os.path.dirname(__file__), "..", "webui", "src", "util", "querySuggest.ts")


def _webui_row_fields():
    with open(WEBUI) as f:
        source = f.read()
    block = source.split("ROW_FIELDS = [", 1)[1].split("]", 1)[0]
    return set(re.findall(r'"([^"]+)"', block))


def test_webui_row_fields_match_the_query_language():
    assert _webui_row_fields() == set(ROW_FIELDS)
