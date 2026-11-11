"""Plan 36 §3: a finalise-only attempt's baseline. A run with no
``children_by`` runs of its own says so ("this attempt has no trade_date runs
of its own", never "no value finished yet"). With ``ui.baseline.pool_by``
(``tags.launch_id``) a run is compared through its training's pooled units:
every outer run sharing its value, the latest attempt winning a key; the
peers are other trainings, chosen by ``match``/``differ`` on each training's
latest attempt."""
import pytest
from leaderboard_group_rows import run, snapshot, v
from vmn_exp.core.app_settings import SettingsError, baseline_rule, parse_settings
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui.baseline_compare import chip
from vmn_exp.ui.baseline_views import BaselineViews
from vmn_exp.ui.job_views import JobViews

SCHEMA = {"best_value": {"goal": "max"}}
BY = "params.trade_date"
RULE = {"match": ["tags.target"], "differ": ["tags.launch_id"], "children_by": BY}
POOLED = dict(RULE, pool_by="tags.launch_id")


def _attempt(n, launch, dates=(), target="t1", tags=None):
    """Outer run *n* of training *launch*: a date run per ``(date, value)``,
    else a finalise run alone (no date)."""
    out = [run(n, tags={"launch_id": launch, "target": target, **(tags or {})})]
    for i, (date, value) in enumerate(dates):
        out.append(run(n + 1 + i, parent=n, params={"trade_date": date},
                       metrics={"best_value": value}))
    if not dates:
        out.append(run(n + 1, parent=n, tags={"kind": "finalise"}))
    return out


def _specs(b1=1.0):
    """Training LB (attempts 10, 20) before LA (30 with three dates, 40
    finalise-only)."""
    return (_attempt(10, "LB", [("d1", b1), ("d2", 1.0), ("d3", 1.0)])
            + _attempt(20, "LB", [("d3", 0.4), ("d4", 1.0)])
            + _attempt(30, "LA", [("d1", 1.2), ("d2", 0.2), ("d3", 1.1)])
            + _attempt(40, "LA"))


def _views(baseline, **ui):
    cache = lb.LeaderboardCache(conf_of=lambda snap: ({}, {"baseline": baseline, **ui}))
    return BaselineViews(JobViews(cache))


def test_a_run_without_children_by_runs_says_so():
    body = _views(RULE).baseline(snapshot(_specs()), SCHEMA, v(40))
    assert body["baseline"]["verstr"] == v(20)
    assert body["chip"]["state"] == "none"
    assert body["chip"]["text"] == "best_value: this attempt has no trade_date runs of its own"
    assert body["pairs_total"] == 0


def test_the_chip_without_own_keys_never_says_nothing_finished():
    out = chip([], [1.0], "best_value", True, BY, 0)
    assert out["state"] == "none" and "finished" not in out["text"]


def test_pool_by_compares_the_training_s_pooled_units():
    views, snap = _views(POOLED), snapshot(_specs())
    body = views.baseline(snap, SCHEMA, v(40))
    assert body["baseline"]["verstr"] == v(20)  # LB's latest attempt
    assert [p["label"] for p in body["pairs"]] == ["d1", "d2", "d3"]
    assert [p["value"] for p in body["pairs"]] == [1.2, 0.2, 1.1]
    assert [p["baseline"] for p in body["pairs"]] == [1.0, 1.0, 0.4]  # d3 from 20
    assert body["pairs_total"] == 3
    assert body["chip"]["state"] == "worse" and body["chip"]["pool_by"] == "tags.launch_id"
    assert body["pool"] == {"by": "tags.launch_id", "attempts": [v(40), v(30)],
                            "baseline_attempts": [v(20), v(10)]}
    assert views.baseline(snap, SCHEMA, v(30))["pairs"] == body["pairs"]


def test_a_pooled_training_without_children_by_runs_says_so():
    specs = _specs() + _attempt(50, "LC") + _attempt(60, "LC")
    body = _views(POOLED).baseline(snapshot(specs), SCHEMA, v(60))
    assert body["chip"]["state"] == "none"
    assert body["chip"]["text"] == "best_value: this training has no trade_date runs in any attempt"


def test_pool_by_compares_the_pooled_rolled_values():
    agg = {"agg": "median", "by": "field:params.trade_date", "value": "own"}
    body = _views(dict(POOLED, children_by=None), job_aggregate=agg).baseline(
        snapshot(_specs()), SCHEMA, v(40))
    assert (body["rolled"]["value"], body["rolled"]["baseline"]) == (1.1, 1.0)
    assert body["chip"]["text"] == "▲ median best_value 1.1 (baseline 1)"


def test_peers_are_other_trainings_chosen_on_their_latest_attempt():
    # LB's latest attempt is for another target: no peer, though 10 matches.
    specs = (_attempt(10, "LB", [("d1", 1.0)]) + _attempt(20, "LB", [("d1", 1.0)], target="t2")
             + _attempt(30, "LA", [("d1", 1.2)]))
    assert _views(POOLED).baseline(snapshot(specs), SCHEMA, v(30))["baseline"] is None
    assert _views(RULE).baseline(snapshot(specs), SCHEMA, v(30))["baseline"]["verstr"] == v(10)


def test_a_pin_on_a_training_s_latest_attempt_picks_it():
    specs = (_attempt(10, "LB", [("d1", 1.0)], tags={"baseline": "true"})
             + _attempt(20, "LC", [("d1", 1.0)]) + _attempt(30, "LA", [("d1", 1.2)]))
    body = _views(POOLED).baseline(snapshot(specs), SCHEMA, v(30))
    assert (body["baseline"]["verstr"], body["baseline"]["source"]) == (v(10), "pinned")


def test_a_run_without_the_pool_field_has_no_baseline():
    specs = _specs() + [run(70, tags={"target": "t1"}), run(71, parent=70, params={"trade_date": "d1"})]
    assert _views(POOLED).baseline(snapshot(specs), SCHEMA, v(70))["baseline"] is None


def test_an_earlier_attempt_changing_moves_the_comparison():
    views = _views(POOLED)
    first = views.baseline(snapshot(_specs()), SCHEMA, v(40))
    again = views.baseline(snapshot(_specs(b1=3.0), generation=2), SCHEMA, v(40))
    assert first["pairs"][0]["baseline"] == 1.0 and again["pairs"][0]["baseline"] == 3.0


def test_pool_by_is_checked_on_save():
    ui = parse_settings("ui:\n  baseline: {pool_by: tags.launch_id, differ: [tags.launch_id]}\n")["ui"]
    assert baseline_rule(ui)["pool_by"] == "tags.launch_id"
    assert baseline_rule({})["pool_by"] is None
    with pytest.raises(SettingsError, match="pool_by"):
        parse_settings("ui:\n  baseline: {pool_by: status}\n")
    with pytest.raises(SettingsError, match="pool_by"):
        parse_settings("ui:\n  baseline: {pool_by: tags.launch_id, match: [tags.launch_id]}\n")
