"""The lean-row decoder beside its encoder: the stored JSON with its idx."""
from vmn_exp.core.index_lean_store import _dumps, decode_row


def test_decode_row_sets_the_idx_column_over_the_stored_one():
    text = _dumps({"verstr": "0.0.1-dev.abc", "idx": 9, "parent": None})
    assert decode_row(3, text) == {"verstr": "0.0.1-dev.abc", "idx": 3, "parent": None}
