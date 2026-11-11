"""Plan 31 §2: settings ``experiment.ui.job_aggregate`` — the Outer runs
row's default aggregate ``{agg, by, value, metric}`` — and the two tails
(``best10``/``worst10``) in the group-by vocabulary."""
import pytest

from vmn_exp.core.app_settings import (
    GROUP_AGGREGATES,
    SettingsError,
    job_aggregate_of,
    parse_settings,
)
from vmn_exp.ui.leaderboard_group_summary import of_sorted, stats

FGM = """\
ui:
  job_aggregate: {agg: median, by: "field:params.trade_date", value: own, metric: date.best_value}
"""


def test_a_job_aggregate_is_kept():
    assert parse_settings(FGM)["ui"]["job_aggregate"] == {
        "agg": "median", "by": "field:params.trade_date", "value": "own",
        "metric": "date.best_value"}
    for by in ("children", "runs", "kind:date", "field:tags.kind"):
        parse_settings(f"ui:\n  job_aggregate: {{by: '{by}'}}\n")


@pytest.mark.parametrize("value", [
    "median",                    # not a mapping
    "{agg: sum}",                # not an aggregate
    "{by: depth}",               # not a unit
    "{by: 'field:metrics.x'}",   # not a param or tag
    "{by: 'field:params.'}",     # no key
    "{by: 'kind:'}",             # no kind
    "{value: last}",             # not a source
    "{metric: ''}",              # no name
    "{metric: 3}",               # not a name
    "{agg: median, extra: 1}",   # unknown field
])
def test_a_bad_job_aggregate_is_refused(value):
    with pytest.raises(SettingsError, match="job_aggregate"):
        parse_settings(f"ui:\n  job_aggregate: {value}\n")


def test_job_aggregate_of_reads_it_or_none_when_invalid():
    assert job_aggregate_of(parse_settings(FGM)["ui"])["by"] == "field:params.trade_date"
    assert job_aggregate_of({"job_aggregate": {"agg": "sum"}}) == {}
    assert job_aggregate_of(None) == {}


def test_the_tails_are_group_aggregates_that_follow_the_goal():
    assert {"best10", "worst10"} <= set(GROUP_AGGREGATES)
    parse_settings("ui:\n  group_aggregate: best10\n")
    ordered = [float(x) for x in range(11)]
    assert of_sorted(ordered, "best10", "max") == 9.0
    assert of_sorted(ordered, "worst10", "max") == 1.0
    assert of_sorted(ordered, "best10", "min") == 1.0
    assert of_sorted(ordered, "worst10", "min") == 9.0
    assert of_sorted(ordered, "best10", None) is None
    assert of_sorted([1.0, 2.0], "best10", "max") == pytest.approx(1.9)
    summary = stats(ordered, "max")
    assert (summary["best10"], summary["worst10"]) == (9.0, 1.0)


def test_nested_is_a_boolean_job_aggregate_field():
    """Plan 36 §2: ``nested: true`` counts carriers at any depth."""
    ui = parse_settings("ui:\n  job_aggregate: {by: 'kind:date', nested: true}\n")["ui"]
    assert job_aggregate_of(ui)["nested"] is True
    with pytest.raises(SettingsError, match="job_aggregate.nested"):
        parse_settings("ui:\n  job_aggregate: {nested: 'yes'}\n")
