"""Plan 35 §2: carriers nested under another carrier. By default
``by=field:<k>``/``kind:<v>`` counts the nearest carrier on each branch and
names the ones it leaves out apart from its ``n``/``of`` (``nested_skipped``:
"median of 11 dates · 3 nested under another date, not counted"); with
``nested`` (``ui.job_aggregate.nested``, URL ``job_agg_nested=1``) it counts
carriers at any depth, a value found twice still a conflict. Pooled group
headers follow the same rule."""
import statistics

import pytest
from leaderboard_group_rows import run, snapshot, v
from vmn_exp.ui.job_aggregate import JobAgg, job_agg_of
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMA = {"best_value": {"goal": "max", "primary": True}, "date.best_value": {"goal": "max"}}
TOP = [f"2024-{m:02d}-01" for m in range(1, 12)]  # 11 dates under the training
NESTED = ["2025-01-01", "2025-02-01", "2025-03-01"]  # one under each of the first 3
DATES = JobAgg(agg="median", by="field:params.trade_date", value="own", metric="date.best_value")
ANY_DEPTH = DATES._replace(nested=True)


def _training(n=1, start=100, launch="L1", nested=NESTED, top=TOP):
    """Training *n* → a date per *top* (``date.best_value`` i/10) → a study →
    a trial; under the first studies, a date of *nested* (2, 3, 4) → a trial."""
    specs, at = [run(n, tags={"kind": "launch", "launch_id": launch})], start
    for i, date in enumerate(top):
        d, study, trial = at, at + 1, at + 2
        at += 3
        specs += [run(d, parent=n, params={"trade_date": date}, tags={"kind": "date"},
                      metrics={"date.best_value": i / 10}),
                  run(study, parent=d, tags={"kind": "study"}),
                  run(trial, parent=study, metrics={"best_value": 0.5})]
        if i < len(nested):
            specs += [run(at, parent=study, params={"trade_date": nested[i]},
                          tags={"kind": "date"}, metrics={"date.best_value": 2 + i}),
                      run(at + 1, parent=at, metrics={"best_value": 0.1})]
            at += 2
    return specs


def _rolled(specs, agg, job=1):
    return LeaderboardCache().job_aggregates.rolled(snapshot(specs), SCHEMA, agg)[v(job)]


@pytest.mark.parametrize("by", ["field:params.trade_date", "kind:date"])
def test_by_default_a_nested_carrier_is_left_out_and_counted(by):
    got = _rolled(_training(), DATES._replace(by=by))
    assert (got["n"], got["of"], got["nested_skipped"], got["conflicts"]) == (11, 11, 3, 0)
    assert got["value"] == pytest.approx(statistics.median([i / 10 for i in range(11)]))
    assert got["nested"] is False


@pytest.mark.parametrize("by", ["field:params.trade_date", "kind:date"])
def test_nested_counts_carriers_at_any_depth(by):
    got = _rolled(_training(), ANY_DEPTH._replace(by=by))
    assert (got["n"], got["of"], got["nested_skipped"], got["conflicts"]) == (14, 14, 0, 0)
    assert got["value"] == pytest.approx(statistics.median([i / 10 for i in range(11)] + [2, 3, 4]))
    assert got["nested"] is True


def test_a_nested_value_seen_twice_is_still_a_conflict():
    specs = _training(nested=[TOP[5]])  # the nested date reruns 2024-06
    got = _rolled(specs, ANY_DEPTH)
    assert (got["n"], got["of"], got["conflicts"]) == (10, 11, 1)


def test_without_nested_carriers_nothing_is_skipped():
    got = _rolled(_training(nested=[]), DATES)
    assert (got["n"], got["of"], got["nested_skipped"]) == (11, 11, 0)


def test_children_and_runs_name_no_nesting():
    for by in ("children", "runs"):
        got = _rolled(_training(), DATES._replace(by=by))
        assert "nested_skipped" not in got and "nested" not in got


def _header(specs, agg):
    (group,) = LeaderboardCache().groups(snapshot(specs), SCHEMA, "tags.launch_id", top="jobs",
                                         job_agg=agg)["groups"]
    return group["job_aggregates"]["date.best_value"]


def test_a_pooled_header_names_the_nested_carriers_left_out():
    # The later attempt reruns the first 2 dates with no nesting.
    specs = _training() + _training(2, start=500, nested=[], top=TOP[:2])
    got = _header(specs, DATES)
    assert (got["n"], got["of"], got["nested_skipped"], got["from_earlier"]) == (11, 11, 3, 9)


def test_a_pooled_header_counts_nested_carriers_with_nested():
    specs = _training() + _training(2, start=500, nested=[], top=TOP[:2])
    got = _header(specs, ANY_DEPTH)
    assert (got["n"], got["of"], got["nested_skipped"], got["from_earlier"]) == (14, 14, 0, 12)


def test_the_app_and_the_url_set_nested():
    ui = {"job_aggregate": {"by": "field:params.trade_date", "nested": True}}
    assert job_agg_of(ui).nested is True
    assert job_agg_of(ui, nested=False).nested is False
    assert job_agg_of({}).nested is False
    assert job_agg_of({}, nested=True).nested is True
