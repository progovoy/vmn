"""``.../experiments-columns`` serves ``group:<field>``: a run's group key
on the grouped board (plan 22 G7), so the Charts tab colours every filtered
run by its group, not only the loaded ones."""
import pytest
from vmn_exp.ui.leaderboard_columns import column_getter, columns_payload

ROWS = [
    {"verstr": "a", "idx": 1, "branch": "main", "metrics": {}, "params": {"lr": 0.1},
     "tags": {"team": "x"}, "code_verstr": "a"},
    {"verstr": "b", "idx": 2, "parent": "a", "forked_from": "a", "metrics": {},
     "params": {}, "code_verstr": "c1"},
]


@pytest.mark.parametrize("field, expected", [
    ("parent", ["(none)", "a"]),
    ("forked_from", ["(none)", "a"]),
    ("rerun_of", ["(none)", "(none)"]),
    ("code_verstr", ["a", "c1"]),
    ("branch", ["main", "(none)"]),
    ("params.lr", ["0.1", "(none)"]),
    ("tags.team", ["x", "(none)"]),
])
def test_group_column_is_the_rows_group_key(field, expected):
    key = f"group:{field}"
    payload = columns_payload(ROWS, [key], total=2)
    assert payload["columns"] == {key: expected}


def test_an_unknown_group_field_is_refused():
    with pytest.raises(ValueError):
        column_getter("group:nope")
