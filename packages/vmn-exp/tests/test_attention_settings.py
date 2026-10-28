"""Plan 28 P1: an app's attention queries, settings/conf
``experiment.ui.attention: [{key, label, query, level: warn|error}]``, at
most 8 — validated when settings are parsed, read tolerantly from a conf."""
import pytest
from vmn_exp.core.app_settings import (
    MAX_ATTENTION,
    SettingsError,
    attention_entries,
    parse_settings,
)

GOOD = """\
ui:
  attention:
    - {key: unstable, label: unstable, query: 'tags.health = "unstable"', level: error}
    - {key: waiting_1h, query: 'status = "created" and timestamp < ago("1h")'}
"""


def test_entries_are_kept_and_read_with_their_defaults():
    settings = parse_settings(GOOD)
    assert attention_entries(settings["ui"]) == [
        {"key": "unstable", "label": "unstable", "query": 'tags.health = "unstable"',
         "level": "error"},
        {"key": "waiting_1h", "label": "waiting_1h",
         "query": 'status = "created" and timestamp < ago("1h")', "level": "warn"},
    ]


def test_no_attention_is_no_entries():
    assert attention_entries({}) == []
    assert attention_entries({"attention": []}) == []


def _ui(entries):
    return {"ui": {"attention": entries}}


def _entry(key="k", **kw):
    return {"key": key, "query": "idx > 1", **kw}


@pytest.mark.parametrize("attention, words", [
    ("idx > 1", "list"),
    ([["idx > 1"]], r"ui\.attention\[0\]"),
    ([{"query": "idx > 1"}], "key"),
    ([_entry(key="")], "key"),
    ([_entry(key="a b")], "key"),
    ([_entry(key=3)], "key"),
    ([_entry(key="stuck")], "stuck"),
    ([_entry(key="failed")], "failed"),
    ([_entry(), _entry()], "twice"),
    ([{"key": "k"}], "query"),
    ([_entry(query="")], "query"),
    ([_entry(query=["idx > 1"])], "query"),
    ([_entry(level="info")], "level"),
    ([_entry(label="")], "label"),
    ([_entry(label=7)], "label"),
    ([_entry(colour="red")], "colour"),
    ([_entry(key=f"k{i}") for i in range(MAX_ATTENTION + 1)], "at most 8"),
])
def test_invalid_attention_is_refused_naming_the_entry(attention, words):
    import yaml

    with pytest.raises(SettingsError, match=words):
        parse_settings(yaml.safe_dump(_ui(attention)))


def test_eight_entries_are_allowed():
    import yaml

    settings = parse_settings(yaml.safe_dump(_ui([_entry(key=f"k{i}") for i in range(8)])))
    assert len(attention_entries(settings["ui"])) == 8


def test_a_conf_with_bad_attention_reads_as_none():
    assert attention_entries({"attention": [{"key": "stuck", "query": "idx > 1"}]}) == []
    assert attention_entries({"attention": "nope"}) == []
