"""``vmn-exp list`` layout (plan 39 B3): rows in storage order indent by
tree depth; any other order is flat, each child naming its parent."""

from vmn_exp.cli.experiment import _format_list_row
from vmn_exp.cli.list_layout import list_layout
from vmn_exp.core.metric_summary import SchemaPolicies


def _row(idx, depth=0, parent=None, verstr=None):
    meta = {"verstr": verstr or f"v{idx}", "depth": depth}
    if parent:
        meta["parent"] = parent
    return {"idx": idx, "meta": meta, "metrics": {}}


def test_storage_order_keeps_depth_indentation():
    rows = [_row(1), _row(2, depth=1, parent="v1"), _row(3, depth=2, parent="v2")]
    assert list_layout(rows) == [(0, ""), (1, ""), (2, "")]


def test_a_single_child_row_keeps_its_indent():
    assert list_layout([_row(2, depth=1, parent="v1")]) == [(1, "")]


def test_sorted_rows_are_flat():
    rows = [_row(3, depth=2, parent="v2"), _row(1), _row(2, depth=1, parent="v1")]
    assert [indent for indent, _ in list_layout(rows)] == [0, 0, 0]


def test_a_sorted_child_names_its_listed_parent_by_idx():
    rows = [_row(2, depth=1, parent="v1"), _row(1)]
    assert list_layout(rows)[0] == (0, "^[1]")


def test_a_sorted_child_names_an_unlisted_parent_by_verstr():
    rows = [_row(3, depth=1, parent="v1"), _row(2)]
    assert list_layout(rows)[0] == (0, "^v1")


def test_top_level_rows_get_no_marker():
    rows = [_row(2), _row(1)]
    assert list_layout(rows) == [(0, ""), (0, "")]


def test_format_list_row_uses_the_given_indent_and_marker():
    row = _row(4, depth=3, parent="v1")
    row["meta"].update(status="succeeded", timestamp="2026-01-01T00:00:00Z")
    line = _format_list_row(row, row["meta"], [], SchemaPolicies({}), 0, "^[1]")
    assert line.startswith("[4] v4 ^[1]  succeeded")
    indented = _format_list_row(row, row["meta"], [], SchemaPolicies({}), 2, "")
    assert indented.startswith("    [4] v4  succeeded")
