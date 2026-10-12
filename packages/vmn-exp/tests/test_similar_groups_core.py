"""Grouping and ordering of similar runs (vmn_exp.core.similar): reruns of one
config and the trials of one sweep fill one slot, shown by their best run."""
from similar_fixtures import FakeSnapshot, run, verstrs
from vmn_exp.core.similar import goal_metric, similar_runs

PARAMS = {"lr": 0.1}


def _target(row):
    return {"row": row, "features": None, "intent": None, "hypothesis": None,
            "text": None, "text_only": False}


def _sweep(*losses, metric="val_loss"):
    outer = run("outer", params={})
    trials = [run(f"t{i}", parent="outer", params=PARAMS, metrics={metric: loss})
              for i, loss in enumerate(losses, 1)]
    return [outer] + trials


def test_reruns_of_one_config_fill_one_slot_with_their_group_size():
    code = run("r1")["code_verstr"]
    rows = [run("r1", code=code, params=PARAMS), run("r2", code=code, params=PARAMS),
            run("x", params=PARAMS)]
    items = similar_runs(FakeSnapshot(rows), _target(run("t", params=PARAMS)))
    assert sorted((i["verstr"] in ("r1", "r2"), i["group_size"]) for i in items) == [
        (False, 1), (True, 2)]


def test_a_sweep_shows_its_best_trial_by_a_min_goal_and_counts_the_outer_run():
    snapshot = FakeSnapshot(_sweep(0.5, 0.3, 0.4), declared={"val_loss": {"goal": "min"}})
    [item] = similar_runs(snapshot, _target(run("t", params=PARAMS)))
    assert item["verstr"] == "t2"
    assert item["group_size"] == 4
    assert item["goal"] == {"metric": "val_loss", "goal": "min", "value": 0.3}


def test_a_max_goal_from_the_conf_schema_picks_the_highest():
    snapshot = FakeSnapshot(_sweep(0.5, 0.9, 0.7, metric="acc"))
    [item] = similar_runs(snapshot, _target(run("t", params=PARAMS)),
                          schema={"acc": {"goal": "max"}})
    assert item["verstr"] == "t2"
    assert item["goal"]["value"] == 0.9


def test_a_glob_goal_counts():
    snapshot = FakeSnapshot(_sweep(0.5, 0.3), declared={"val_*": {"goal": "min"}})
    [item] = similar_runs(snapshot, _target(run("t", params=PARAMS)))
    assert item["verstr"] == "t2"


def test_without_a_goal_the_group_shows_its_most_similar_run():
    rows = _sweep(0.5, 0.3)
    rows[1] = dict(rows[1], params={"lr": 0.1, "bs": 8})
    [item] = similar_runs(FakeSnapshot(rows), _target(run("t", params={"lr": 0.1, "bs": 8})))
    assert item["verstr"] == "t1"
    assert item["goal"] is None


def test_trials_without_the_goal_metric_lose_to_those_with_it():
    rows = _sweep(0.5, 0.3)
    rows.append(run("t3", parent="outer", params=PARAMS, metrics={"other": 0.0}))
    snapshot = FakeSnapshot(rows, declared={"val_loss": {"goal": "min"}})
    [item] = similar_runs(snapshot, _target(run("t", params=PARAMS)))
    assert item["verstr"] == "t2"


def test_the_goal_metric_is_the_one_most_rows_carry():
    rows = [run("a", metrics={"loss": 1.0, "acc": 0.5}), run("b", metrics={"loss": 2.0})]
    schema = {"acc": {"goal": "max"}, "loss": {"goal": "min"}}
    assert goal_metric(schema, rows) == ("loss", "min")
    assert goal_metric({}, rows) is None
    assert goal_metric(schema, [run("c", metrics={"acc": float("nan")})]) is None


def test_ties_order_by_newest_then_verstr():
    rows = [
        run("b", params=PARAMS, timestamp="2026-01-01T00:00:00Z"),
        run("a", params=PARAMS, timestamp="2026-01-01T00:00:00Z"),
        run("new", params=PARAMS, timestamp="2026-02-01T00:00:00Z"),
        run("undated", params=PARAMS, timestamp=None),
    ]
    items = similar_runs(FakeSnapshot(rows), _target(run("t", params=PARAMS)))
    assert len({i["score"] for i in items}) == 1
    assert verstrs(items) == ["new", "a", "b", "undated"]


def test_scores_sort_descending():
    rows = [run("half", params={"lr": 0.1, "bs": 2}), run("full", params=PARAMS)]
    items = similar_runs(FakeSnapshot(rows), _target(run("t", params=PARAMS)))
    assert verstrs(items) == ["full", "half"]
    assert items[0]["score"] > items[1]["score"]


def _nested_sweep(*losses, outer=True):
    """outer -> trials t<i> -> the SDK runs s<i> their script opened (auto-parented)."""
    rows = [run("outer", params={})] if outer else []
    for i, loss in enumerate(losses, 1):
        rows.append(run(f"t{i}", parent="outer", params={}))
        rows.append(run(f"s{i}", parent=f"t{i}", params=PARAMS, metrics={"val_loss": loss}))
    return rows


def test_a_nested_sweep_fills_one_slot_shown_by_its_best_sdk_run():
    snapshot = FakeSnapshot(_nested_sweep(0.5, 0.2, 0.4), declared={"val_loss": {"goal": "min"}})
    [item] = similar_runs(snapshot, _target(run("t", params=PARAMS)))
    assert item["verstr"] == "s2"
    assert item["group_size"] == 7
    assert item["goal"] == {"metric": "val_loss", "goal": "min", "value": 0.2}


def test_a_nested_sweep_whose_outer_run_is_missing_still_fills_one_slot():
    rows = _nested_sweep(0.5, 0.9, outer=False)
    [item] = similar_runs(FakeSnapshot(rows), _target(run("t", params=PARAMS)),
                          schema={"val_loss": {"goal": "max"}})
    assert (item["verstr"], item["group_size"]) == ("s2", 4)


def test_a_parent_cycle_ends_the_walk_in_one_group():
    rows = [run("a", parent="b", params=PARAMS), run("b", parent="a", params=PARAMS)]
    [item] = similar_runs(FakeSnapshot(rows), _target(run("t", params=PARAMS)))
    assert item["group_size"] == 2
