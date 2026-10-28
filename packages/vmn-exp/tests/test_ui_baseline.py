"""Plan 28 N3, the pure part: an outer run's baseline is the latest ended
outer run beside it with equal values on the match fields, unless one is
pinned with ``tags.baseline = "true"``; their direct children pair by a key
field, each pair with the delta of the main metric in key order, and the
chip counts the finished pairs worse than the baseline's worst decile."""
from vmn_exp.ui.baseline_choice import choose_baseline
from vmn_exp.ui.baseline_compare import chip, delta, pair_children, rollup_deltas

MATCH = ["params.table_name", "params.model_type"]


def _launch(n, table="t1", model="m1", status="succeeded", tags=None, parent=None):
    return {"verstr": f"v{n}", "idx": n, "timestamp": f"2026-01-{n:02d}T00:00:00Z",
            "status": status, "parent": parent, "tags": tags or {},
            "params": {"table_name": table, "model_type": model}}


def test_the_latest_ended_launch_with_equal_values_is_the_baseline():
    target = _launch(9, status="running")
    candidates = [_launch(1), _launch(4), _launch(5, model="m2"), _launch(6, status="running"),
                  _launch(12)]
    row, source = choose_baseline(target, candidates, MATCH)
    assert (row["verstr"], source) == ("v4", "latest")


def test_a_pinned_launch_beats_the_latest():
    target = _launch(9)
    candidates = [_launch(1, tags={"baseline": "true"}), _launch(4),
                  _launch(3, model="m2", tags={"baseline": "true"})]
    row, source = choose_baseline(target, candidates, MATCH)
    assert (row["verstr"], source) == ("v1", "pinned")


def test_no_match_fields_take_the_latest_ended_launch():
    row, _ = choose_baseline(_launch(9), [_launch(1, table="x"), _launch(2, table="y")], [])
    assert row["verstr"] == "v2"


def test_nothing_alike_is_no_baseline():
    assert choose_baseline(_launch(9), [_launch(1, table="x"), _launch(9)], MATCH) == (None, None)


def test_a_delta_knows_which_way_is_better():
    assert delta(0.8, 1.0, higher_better=True) == {
        "value": 0.8, "baseline": 1.0, "delta": -0.2, "better": False}
    assert delta(10.0, 12.5, higher_better=False)["better"] is True
    assert delta(3.0, 3.0, higher_better=False)["better"] is None
    assert delta(None, 1.0, higher_better=True) == {
        "value": None, "baseline": 1.0, "delta": None, "better": None}


def _rollup(best, median, failed_pct, p90):
    return {"metrics": {"best_value": {"best": best, "p50": median}},
            "failed_pct": failed_pct, "duration": {"p90": p90}}


def test_rollup_deltas_cover_metrics_failures_and_duration():
    out = rollup_deltas(_rollup(1.1, 0.9, 5.0, 300.0), _rollup(1.2, 0.8, 2.0, 600.0),
                        {"best_value": True})
    assert out["metrics"]["best_value"]["best"]["better"] is False
    assert out["metrics"]["best_value"]["median"]["better"] is True
    assert out["failed_pct"] == {"value": 5.0, "baseline": 2.0, "delta": 3.0, "better": False}
    assert out["duration_p90"]["better"] is True


def test_a_goal_less_metric_has_no_best_and_no_direction():
    out = rollup_deltas(_rollup(None, 0.9, 0, 1), _rollup(None, 0.8, 0, 1), {"best_value": None})
    assert out["metrics"]["best_value"]["best"]["delta"] is None
    assert out["metrics"]["best_value"]["median"]["better"] is None


def _date(n, date, value, status="succeeded", ts=None):
    return {"verstr": f"c{n}", "idx": n, "status": status, "timestamp": ts or f"2026-02-{n:02d}",
            "params": {"trade_date": date}, "metrics": {"best_value": value}}


def _value(row):
    return row["metrics"].get("best_value")


def test_children_pair_by_key_in_key_order():
    target = [_date(1, "2024-12", 0.5), _date(2, "2024-06", 1.0), _date(3, "2025-06", 0.7,
                                                                        status="running"),
              _date(4, "2026-01", 0.9)]
    baseline = [_date(11, "2024-06", 1.1), _date(12, "2024-12", 1.0),
                _date(13, "2025-06", 0.9)]
    pairs, total = pair_children(target, baseline, "params.trade_date", _value, True)
    assert [p["label"] for p in pairs] == ["2024-06", "2024-12", "2025-06"]
    assert total == 4
    first = pairs[0]
    assert (first["verstr"], first["baseline_verstr"], first["done"]) == ("c2", "c11", True)
    assert first["delta"] == -0.1 and first["better"] is False
    assert pairs[2]["done"] is False


def test_a_retried_key_pairs_its_latest_run():
    target = [_date(1, "d1", 0.1, ts="2026-02-01"), _date(2, "d1", 0.9, ts="2026-02-02")]
    pairs, _ = pair_children(target, [_date(3, "d1", 1.0)], "params.trade_date", _value, True)
    assert [p["verstr"] for p in pairs] == ["c2"]


def _pairs(values, base=1.0, done=True):
    return [{"key": f"d{i}", "label": f"d{i}", "value": v, "baseline": base, "done": done,
             "delta": None if v is None else v - base} for i, v in enumerate(values)]


def test_the_chip_counts_finished_dates_worse_than_the_baselines_p10():
    pairs = _pairs([1.0, 0.2, 1.1, 0.1, 0.95]) + _pairs([0.0], done=False)
    out = chip(pairs, [0.9, 1.0, 1.0, 1.1, 1.2], "best_value", True, "params.trade_date")
    assert out["state"] == "worse"
    assert (out["worse"], out["of"], out["from"]) == (2, 5, "d1")
    assert out["text"] == ("▼ best_value from d1 (2 of 5 trade_date values worse than the "
                           "baseline's p10)")
    assert [p.get("worse") for p in pairs[:5]] == [False, True, False, True, False]


def test_a_lower_is_better_metric_uses_the_p90():
    out = chip(_pairs([2.0, 0.5]), [0.4, 0.5, 0.6], "loss", False, "params.trade_date")
    assert out["state"] == "worse" and out["quantile"] == "p90" and out["worse"] == 1


def test_no_date_worse_and_better_on_the_median_is_better():
    out = chip(_pairs([1.2, 1.3], base=1.0), [1.0, 1.0], "best_value", True, "params.trade_date")
    assert out["state"] == "better" and out["text"].startswith("▲ best_value (none of 2")


def test_nothing_finished_yet_is_pending():
    out = chip(_pairs([0.1], done=False), [1.0], "best_value", True, "params.trade_date")
    assert out["state"] == "pending" and out["of"] == 0


def test_a_goal_less_metric_has_no_chip():
    assert chip(_pairs([0.1]), [1.0], "value", None, "params.trade_date") is None
