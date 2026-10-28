"""Plan 28 N3: an app's baseline rule, settings/conf ``experiment.ui.baseline:
{match: [<field>...], children_by: <field>}`` (fields ``params.<k>`` /
``tags.<k>``) — validated when settings are parsed, read tolerantly from a
conf, and the same field check for a URL's ``match=``/``by=``."""
import pytest
from vmn_exp.core.app_settings import (
    MAX_BASELINE_MATCH,
    SettingsError,
    baseline_conf,
    baseline_fields,
    parse_settings,
)

GOOD = """\
ui:
  baseline:
    match: [params.table_name, params.model_type]
    children_by: params.trade_date
"""


def test_the_rule_is_kept_and_read():
    settings = parse_settings(GOOD)
    assert baseline_conf(settings["ui"]) == {
        "match": ["params.table_name", "params.model_type"], "children_by": "params.trade_date"}


@pytest.mark.parametrize("ui", [{}, {"baseline": {}}, {"baseline": None}])
def test_no_rule_matches_nothing_and_pairs_nothing(ui):
    assert baseline_conf(ui) == {"match": [], "children_by": None}


def test_an_invalid_rule_in_a_conf_reads_as_none():
    assert baseline_conf({"baseline": {"match": "params.a"}}) == {"match": [], "children_by": None}


@pytest.mark.parametrize("baseline, words", [
    ("params.a", "mapping"),
    ({"match": "params.a"}, "list"),
    ({"match": ["status"]}, r"ui\.baseline\.match\[0\]"),
    ({"match": ["params."]}, "params"),
    ({"match": [3]}, "match"),
    ({"match": ["params.a", "params.a"]}, "twice"),
    ({"match": [f"params.k{i}" for i in range(MAX_BASELINE_MATCH + 1)]}, "at most"),
    ({"children_by": "branch"}, "children_by"),
    ({"children_by": ["params.d"]}, "children_by"),
    ({"pin": "tags.baseline"}, "pin"),
])
def test_invalid_rules_are_refused_naming_the_key(baseline, words):
    import yaml

    with pytest.raises(SettingsError, match=words):
        parse_settings(yaml.safe_dump({"ui": {"baseline": baseline}}))


def test_url_fields_are_a_comma_separated_list():
    assert baseline_fields("params.a, tags.b") == ["params.a", "tags.b"]
    assert baseline_fields("") == []


@pytest.mark.parametrize("text", ["status", "params.a,params.a", "params.a,,"])
def test_bad_url_fields_are_refused(text):
    with pytest.raises(SettingsError):
        baseline_fields(text)
