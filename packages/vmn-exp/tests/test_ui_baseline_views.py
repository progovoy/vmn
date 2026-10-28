"""Plan 28 N3 over an index snapshot: an outer run's baseline (chosen by the
app's ``experiment.ui.baseline`` rule, a pin or ``to``), the rollup deltas,
attention shares, children paired by key and the chip; memoized per
generation, a settled pair kept until either subtree changes."""
import pytest
from leaderboard_group_rows import run, snapshot, v
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.ui import baseline_views as views_mod
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui.baseline_views import BaselineViews, UnknownBaseline
from vmn_exp.ui.job_views import JobViews

SCHEMA = {"best_value": {"goal": "max"}}
RULE = {"baseline": {"match": ["params.table_name", "params.model_type"],
                     "children_by": "params.trade_date"}}
DATES = ["2024-06", "2024-12", "2025-06", "2025-12"]


def _launch(n, start, values, model="m1", state="ok", child_state="ok", tags=None):
    """Launch *n* and a date run per value of *values* (runs *start*...)."""
    out = [run(n, state=state, params={"table_name": "t1", "model_type": model}, tags=tags)]
    for i, value in enumerate(values):
        out.append(run(start + i, state=child_state, parent=n, params={"trade_date": DATES[i]},
                       metrics={} if value is None else {"best_value": value}))
    return out


def _specs(target_state="ok", target_tags=None, child_state="ok"):
    return (_launch(1, 10, [1.0, 1.0, 1.0, 1.0])
            + _launch(2, 20, [9.0, 9.0], model="m2")
            + _launch(3, 30, [1.1, 0.2, 0.1, 1.2], state=target_state, child_state=child_state,
                      tags=target_tags)
            + [run(n) for n in range(40, 45)])


def _views(conf=RULE):
    cache = lb.LeaderboardCache(conf_of=lambda snap: ({}, conf))
    return BaselineViews(JobViews(cache))


def test_the_latest_ended_alike_launch_is_compared():
    body = _views().baseline(snapshot(_specs()), SCHEMA, v(3))
    assert body["baseline"]["verstr"] == v(1) and body["baseline"]["source"] == "latest"
    assert body["match"] == ["params.table_name", "params.model_type"]
    assert body["by"] == "params.trade_date"
    assert [p["label"] for p in body["pairs"]] == DATES
    assert [p["delta"] for p in body["pairs"]] == [0.1, -0.8, -0.9, 0.2]
    assert body["chip"]["state"] == "worse"
    assert body["chip"]["text"].startswith("▼ best_value from 2024-12 (2 of 4")
    assert body["metrics"]["best_value"]["best"] == {
        "value": 1.2, "baseline": 1.0, "delta": 0.2, "better": True}
    assert body["failed_pct"]["delta"] == 0.0


def test_to_overrides_the_rule_and_a_url_match_overrides_the_conf():
    views, snap = _views(), snapshot(_specs())
    assert views.baseline(snap, SCHEMA, v(3), to=v(2))["baseline"]["source"] == "to"
    body = views.baseline(snap, SCHEMA, v(1), match=[])
    assert body["baseline"] is None  # every other launch is later than v1
    assert views.baseline(snap, SCHEMA, v(3), match=["params.model_type"])["baseline"][
        "verstr"] == v(1)


def test_a_pinned_launch_is_compared():
    specs = _specs()
    specs[0] = run(1, params={"table_name": "t1", "model_type": "m1"},
                   tags={"baseline": "true"})
    body = _views().baseline(snapshot(specs), SCHEMA, v(3))
    assert body["baseline"]["source"] == "pinned"


def test_no_alike_launch_is_no_baseline():
    body = _views().baseline(snapshot(_specs()), SCHEMA, v(2))
    assert body["baseline"] is None and body["chip"] is None and body["pairs"] == []


def test_a_bad_to_is_refused():
    views, snap = _views(), snapshot(_specs())
    with pytest.raises(UnknownBaseline):
        views.baseline(snap, SCHEMA, v(3), to=v(99))
    with pytest.raises(UnknownBaseline):
        views.baseline(snap, SCHEMA, v(3), to=v(40))  # not an outer run
    with pytest.raises(ValueError):
        views.baseline(snap, SCHEMA, v(3), to=v(3))


def test_without_children_by_the_chip_is_the_best_values_change():
    conf = {"baseline": {"match": ["params.table_name", "params.model_type"]}}
    body = _views(conf).baseline(snapshot(_specs()), SCHEMA, v(3))
    assert body["pairs"] == [] and body["chip"]["state"] == "better"
    assert body["chip"]["text"] == "▲ best_value 1.2 (baseline 1)"


def test_a_live_launch_shows_what_finished_so_far():
    specs = _specs(target_state="running")
    next(s for s in specs if s["n"] == 32)["state"] = "running"
    body = _views().baseline(snapshot(specs), SCHEMA, v(3))
    assert [p["done"] for p in body["pairs"]] == [True, True, False, True]
    assert (body["chip"]["worse"], body["chip"]["of"]) == (1, 3)


def test_a_child_outer_run_pairs_by_its_subtree_best():
    specs = _specs() + [run(50, parent=13, metrics={"best_value": 0.5}),
                        run(51, parent=33, metrics={"best_value": 2.0})]
    specs = [dict(s, metrics={}) if s["n"] in (13, 33) else s for s in specs]
    body = _views().baseline(snapshot(specs), SCHEMA, v(3))
    assert body["pairs"][3]["value"] == 2.0 and body["pairs"][3]["baseline"] == 0.5


def test_attention_shares_under_each_subtree():
    entries = [{"key": "weak", "label": "weak", "level": "warn",
                "query": "metrics.best_value < 0.5"}]
    body = _views().baseline(snapshot(_specs()), SCHEMA, v(3), attention=entries)
    weak = body["attention"][0]
    assert (weak["count"], weak["baseline_count"]) == (2, 0)
    assert weak["value"] == 0.5 and weak["better"] is False


def test_own_metrics_both_launches_log_are_compared():
    specs = _specs()
    specs[0]["metrics"] = {"cost_per_date": 4.0}
    specs[next(i for i, s in enumerate(specs) if s["n"] == 3)]["metrics"] = {"cost_per_date": 5.0}
    body = _views().baseline(snapshot(specs), SCHEMA, v(3))
    assert body["own"]["cost_per_date"]["delta"] == 1.0


def test_chips_for_many_rows():
    chips = _views().chips(snapshot(_specs()), SCHEMA, [v(3), v(2), v(40), v(99)])
    assert chips[v(3)]["state"] == "worse" and chips[v(3)]["baseline"]["verstr"] == v(1)
    assert chips[v(2)] is None and chips[v(40)] is None and chips[v(99)] is None


def _next(snap, replace=None):
    replace = replace or {}
    rows = [replace.get(row["verstr"], row) for row in snap.rows]
    return IndexSnapshot.build(snap.app_name, snap.generation + 1, rows, dict(snap.run_states))


@pytest.fixture
def builds(monkeypatch):
    calls = []
    real = views_mod.pair_children

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(views_mod, "pair_children", counted)
    return calls


def test_a_settled_pair_outlives_generations_outside_it(builds):
    views, snap = _views(), snapshot(_specs())
    first = views.baseline(snap, SCHEMA, v(3))
    tag = views.etag(snap, SCHEMA, v(3))
    for n in (40, 41, 42):
        snap = _next(snap, {v(n): dict(snap.row(v(n)), note="edited")})
        assert views.baseline(snap, SCHEMA, v(3)) == first
        assert views.etag(snap, SCHEMA, v(3)) == tag
    assert len(builds) == 1


def test_a_change_under_the_baseline_builds_it_again(builds):
    views, snap = _views(), snapshot(_specs())
    views.baseline(snap, SCHEMA, v(3))
    row = snap.row(v(11))
    snap = _next(snap, {v(11): dict(row, metrics={"best_value": 0.1})})
    assert views.baseline(snap, SCHEMA, v(3))["pairs"][1]["baseline"] == 0.1
    assert len(builds) == 2


def test_a_live_launch_is_built_per_generation(builds):
    views, snap = _views(), snapshot(_specs(target_state="running"))
    views.baseline(snap, SCHEMA, v(3))
    views.baseline(snap, SCHEMA, v(3))
    snap = _next(snap, {v(40): dict(snap.row(v(40)), note="edited")})
    views.baseline(snap, SCHEMA, v(3))
    assert len(builds) == 2


def test_attention_parts_pair_by_key_when_a_built_in_shows_on_one_side():
    """Target run 33 still runs under its ended launch (outlived); the
    baseline has none, so the built-in part shows on our side only."""
    from vmn_exp.ui.attention_built_in import with_built_in

    specs = _specs()
    specs[next(i for i, s in enumerate(specs) if s["n"] == 33)]["state"] = "running"
    entries = with_built_in([{"key": "weak", "label": "weak", "level": "warn",
                              "query": "metrics.best_value < 0.5"}])
    body = _views().baseline(snapshot(specs), SCHEMA, v(3), attention=entries)
    parts = {p["key"]: (p["count"], p["baseline_count"]) for p in body["attention"]}
    assert parts == {"outlived": (1, 0), "weak": (2, 0)}
