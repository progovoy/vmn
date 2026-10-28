"""Plan 28 N6: settings ``experiment.ui.tree_columns`` — the tree's columns
per ``tags.kind`` value, each a list of board show keys."""
import pytest

from vmn_exp.core.app_settings import SettingsError, parse_settings, tree_columns_of

GOOD = """\
ui:
  tree_columns:
    study: [m:best_value, p:group, c:duration]
    refit: [t:health, c:ratio]
"""


def test_tree_columns_are_kept():
    assert parse_settings(GOOD)["ui"]["tree_columns"] == {
        "study": ["m:best_value", "p:group", "c:duration"], "refit": ["t:health", "c:ratio"]}


@pytest.mark.parametrize("value", [
    "[m:loss]",                 # not a mapping
    "{study: m:loss}",          # not a list
    "{study: [loss]}",          # no column prefix
    "{study: ['x:loss']}",      # unknown prefix
    "{study: ['m:']}",          # no name
    "{study: [1]}",             # not a string
    "{'': [m:loss]}",           # empty kind
])
def test_bad_tree_columns_are_refused(value):
    with pytest.raises(SettingsError, match="tree_columns"):
        parse_settings(f"ui:\n  tree_columns: {value}\n")


def test_tree_columns_of_reads_them_or_none_when_invalid():
    assert tree_columns_of(parse_settings(GOOD)["ui"])["refit"] == ["t:health", "c:ratio"]
    assert tree_columns_of({"tree_columns": {"study": ["nope"]}}) == {}
    assert tree_columns_of(None) == {}
