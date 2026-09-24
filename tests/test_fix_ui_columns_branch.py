"""``.../experiments-columns`` serves ``branch``: the leaderboard's grouped
chart groups every filtered run by it."""
from version_stamp.ui.leaderboard_columns import column_getter, columns_payload


def test_branch_is_a_column():
    rows = [
        {"verstr": "a", "idx": 1, "branch": "main", "metrics": {}, "params": {}},
        {"verstr": "b", "idx": 2, "metrics": {}, "params": {}},
    ]
    payload = columns_payload(rows, ["branch"], total=2)
    assert payload["columns"] == {"branch": ["main", None]}


def test_unknown_keys_are_still_refused():
    import pytest

    with pytest.raises(ValueError):
        column_getter("nope")
