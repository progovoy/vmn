"""Plan 22 S1 (K1, G3): the grouped leaderboard — runs grouped by a link
(``parent``, ``forked_from``, ``rerun_of``, ``code_verstr``) or a field
(``branch``, ``status``, ``tags.<k>``, ``params.<k>``)."""
import pytest
from leaderboard_group_rows import group_of, keys, members, run, snapshot, v
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_group_fields import NONE


def _groups(specs, group, schema=None, **params):
    return LeaderboardCache().groups(snapshot(specs, schema=schema), schema or {}, group, **params)


FLEET = [
    run(1), run(2, parent=1), run(3, parent=1),
    run(4), run(5, parent=4), run(6),
]


def test_parent_groups_put_the_outer_run_in_the_header_not_among_its_rows():
    out = _groups(FLEET, "parent")
    assert keys(out) == [v(1), v(4), NONE]
    outer = group_of(out, v(1))
    assert members(outer) == [v(2), v(3)]
    assert outer["target"]["verstr"] == v(1)
    assert outer["target"]["idx"] == 1
    assert outer["label"] == v(1)
    assert out["total_groups"] == 3
    assert out["total_rows"] == 6


def test_runs_without_a_parent_are_rows_of_the_no_parent_group_shown_last():
    group = group_of(_groups(FLEET, "parent"), NONE)
    assert members(group) == [v(1), v(4), v(6)]
    assert group["target"] is None
    assert group["label"] == "(no parent run)"


def test_an_inner_outer_run_is_a_header_and_a_row_of_its_parents_group():
    out = _groups([run(1), run(2, parent=1), run(3, parent=2)], "parent")
    assert members(group_of(out, v(1))) == [v(2)]
    assert members(group_of(out, v(2))) == [v(3)]
    assert members(group_of(out, NONE)) == [v(1)]


def test_a_target_missing_from_the_index_groups_under_its_verstr():
    group = group_of(_groups([run(1), run(2, parent=99)], "parent"), v(99))
    assert group["target"] is None
    assert group["label"] == f"{v(99)} (not found)"
    assert members(group) == [v(2)]


@pytest.mark.parametrize("link", ["forked_from", "rerun_of"])
def test_fork_and_rerun_groups_are_headed_by_the_run_they_point_at(link):
    out = _groups([run(1), run(2, **{link: 1}), run(3, **{link: 1}), run(4)], link)
    assert keys(out) == [v(1), NONE]
    assert members(group_of(out, v(1))) == [v(2), v(3)]
    assert group_of(out, v(1))["target"]["verstr"] == v(1)
    assert group_of(out, NONE)["label"] == "(none)"


def test_same_code_groups_have_no_target_and_the_code_verstr_as_label():
    code = "0.1.0-dev.e71c74d.ba02c10"
    out = _groups([run(1, code_verstr=code), run(2), run(3, code_verstr=code)], "code_verstr")
    group = group_of(out, code)
    assert members(group) == [v(1), v(3)]
    assert group["target"] is None
    assert group["label"] == code


@pytest.mark.parametrize("group,specs,want", [
    ("branch", [run(1, branch="main"), run(2, branch="dev"), run(3, branch="main")],
     {"main": [v(1), v(3)], "dev": [v(2)]}),
    ("params.lr", [run(1, params={"lr": 0.1}), run(2, params={"lr": 0.01}),
                   run(3, params={"lr": 0.1}), run(4)],
     {"0.1": [v(1), v(3)], "0.01": [v(2)], NONE: [v(4)]}),
    ("tags.team", [run(1, tags={"team": "a"}), run(2)], {"a": [v(1)], NONE: [v(2)]}),
    ("status", [run(1), run(2, state="fail"), run(3)],
     {"succeeded": [v(1), v(3)], "failed": [v(2)]}),
])
def test_field_groups(group, specs, want):
    out = _groups(specs, group)
    assert {g["key"]: members(g) for g in out["groups"]} == want
    assert all(g["target"] is None for g in out["groups"])
    assert keys(out)[-1] == NONE or NONE not in want


def test_field_group_labels_name_the_field():
    out = _groups([run(1, branch="main"), run(2, params={"lr": 0.1})], "params.lr")
    assert group_of(out, "0.1")["label"] == "params.lr = 0.1"
    assert group_of(_groups([run(1)], "branch"), "main")["label"] == "branch = main"


def test_counts_tally_the_groups_rows_by_status():
    specs = [run(1), run(2, parent=1), run(3, parent=1, state="fail"),
             run(4, parent=1, state="running"), run(5, parent=1, state=None)]
    group = group_of(_groups(specs, "parent"), v(1))
    assert group["counts"] == {"total": 4, "running": 1, "waiting": 1, "done": 1,
                               "failed": 1, "stuck": 0}
    assert group["rows_total"] == 4


LOSSES = [1.0, 2.0, 3.0, 10.0, float("nan")]


def _loss_group(schema=None):
    specs = [run(1)] + [run(i + 2, parent=1, metrics={"loss": x}) for i, x in enumerate(LOSSES)]
    specs.append(run(9, parent=1))  # no loss at all
    return group_of(_groups(specs, "parent", schema=schema), v(1))


def test_aggregates_cover_the_finite_values_only():
    agg = _loss_group({"loss": {"goal": "min"}})["aggregates"]["loss"]
    assert agg == {"mean": 4.0, "best": 1.0, "median": 2.5, "min": 1.0, "max": 10.0, "n": 4}


def test_best_follows_the_goal_and_is_null_without_one():
    assert _loss_group({"loss": {"goal": "max"}})["aggregates"]["loss"]["best"] == 10.0
    assert _loss_group({"loss_*": {"goal": "max"}, "lo*": {"goal": "max"}})[
        "aggregates"]["loss"]["best"] == 10.0  # a glob goal counts
    assert _loss_group()["aggregates"]["loss"]["best"] is None


def test_aggregates_take_each_runs_value_by_the_summary_policy():
    log = [{"timestamp": "t", "type": "metrics", "values": {"loss": 0.5}}]
    specs = [run(1), run(2, parent=1, metrics={"loss": 3.0}, log=log),
             run(3, parent=1, metrics={"loss": 2.0}, log=log)]
    schema = {"loss": {"summary": "max"}}
    agg = group_of(_groups(specs, "parent", schema=schema), v(1))["aggregates"]["loss"]
    assert (agg["min"], agg["max"]) == (2.0, 3.0)


def test_a_link_target_carries_its_own_values():
    specs = [run(1, metrics={"loss": 0.91}), run(2, parent=1, metrics={"loss": 0.5})]
    target = group_of(_groups(specs, "parent"), v(1))["target"]
    assert target["metrics"] == {"loss": 0.91}
    assert target["status"] == "succeeded"
    assert target["tree_status"] == "succeeded"
    assert set(target) == {"verstr", "idx", "name", "status", "tree_status", "metrics"}


def test_a_reruns_group_counts_the_originals_value_in_its_aggregates():
    specs = [run(1, metrics={"loss": 1.0}), run(2, rerun_of=1, metrics={"loss": 3.0}),
             run(3, rerun_of=1, metrics={"loss": 5.0})]
    group = group_of(_groups(specs, "rerun_of"), v(1))
    assert group["aggregates"]["loss"]["mean"] == 3.0
    assert group["aggregates"]["loss"]["n"] == 3
    assert group["counts"]["total"] == 2  # the original is the header, not a row


def _two_sweeps():
    # sweep 1: losses 1 and 9 (mean 5); sweep 4: 3 and 4 (mean 3.5)
    return [run(1), run(2, parent=1, metrics={"loss": 9.0}), run(3, parent=1, metrics={"loss": 1.0}),
            run(4), run(5, parent=4, metrics={"loss": 3.0}), run(6, parent=4, metrics={"loss": 4.0})]


@pytest.mark.parametrize("agg,order", [
    ("mean", [4, 1]), ("median", [4, 1]), ("min", [1, 4]), ("max", [4, 1]), ("best", [1, 4]),
])
def test_agg_picks_the_aggregate_groups_sort_by(agg, order):
    out = _groups(_two_sweeps(), "parent", schema={"loss": {"goal": "min"}}, sort="loss", agg=agg)
    assert keys(out) == [v(n) for n in order] + [NONE]


def test_the_default_aggregate_is_the_mean():
    out = _groups(_two_sweeps(), "parent", schema={"loss": {"goal": "min"}}, sort="loss")
    assert keys(out) == [v(4), v(1), NONE]


def test_rows_within_a_group_follow_the_sort_and_order_flips_groups_too():
    schema = {"loss": {"goal": "min"}}
    out = _groups(_two_sweeps(), "parent", schema=schema, sort="loss")
    assert members(group_of(out, v(1))) == [v(3), v(2)]
    flipped = _groups(_two_sweeps(), "parent", schema=schema, sort="loss", order="desc")
    assert keys(flipped) == [v(1), v(4), NONE]
    assert members(group_of(flipped, v(1))) == [v(2), v(3)]


def test_best_on_a_goal_less_metric_sorts_by_the_mean():
    out = _groups(_two_sweeps(), "parent", sort="loss", agg="best")
    assert keys(out) == [v(4), v(1), NONE]


def test_groups_without_a_value_sort_after_the_valued_ones():
    specs = _two_sweeps() + [run(7), run(8, parent=7)]
    out = _groups(specs, "parent", schema={"loss": {"goal": "min"}}, sort="loss", order="desc")
    assert keys(out) == [v(1), v(4), v(7), NONE]


def test_a_date_sort_orders_groups_by_their_first_row():
    specs = [run(1), run(2, parent=1), run(3), run(4, parent=3), run(5, parent=1)]
    out = _groups(specs, "parent", sort="timestamp")  # newest first
    assert keys(out) == [v(1), v(3), NONE]
    assert members(group_of(out, v(1))) == [v(5), v(2)]


def test_filters_cut_rows_and_keep_the_link_header():
    specs = [run(1, metrics={"loss": 9.0}), run(2, parent=1, metrics={"loss": 1.0}),
             run(3, parent=1, metrics={"loss": 8.0}), run(4), run(5, parent=4, metrics={"loss": 7.0})]
    out = _groups(specs, "parent", query="metrics.loss < 5")
    assert keys(out) == [v(1)]  # sweep 4 and the root runs have no passing row
    group = group_of(out, v(1))
    assert members(group) == [v(2)]
    assert group["target"]["verstr"] == v(1)  # failed the filter, still names the group
    assert group["counts"]["total"] == 1
    assert out["total_rows"] == 1


def test_a_status_filter_cuts_rows():
    specs = [run(1), run(2, parent=1, state="fail"), run(3, parent=1)]
    group = group_of(_groups(specs, "parent", status="failed"), v(1))
    assert members(group) == [v(2)]


def test_groups_page_and_each_groups_rows_are_capped():
    specs = [run(1)] + [run(i, parent=1, metrics={"loss": i}) for i in range(2, 30)]
    specs += [run(40), run(41, parent=40), run(50), run(51, parent=50)]
    cache, snap = LeaderboardCache(), snapshot(specs)
    first = cache.groups(snap, {}, "parent", offset=0, limit=2, rows_per_group=5)
    assert keys(first) == [v(1), v(40)]
    assert len(group_of(first, v(1))["rows"]) == 5
    assert group_of(first, v(1))["rows_total"] == 28
    assert first["total_groups"] == 4
    assert first["total_rows"] == len(specs)
    second = cache.groups(snap, {}, "parent", offset=2, limit=2)
    assert keys(second) == [v(50), NONE]


def test_group_key_pages_one_groups_rows():
    specs = [run(1)] + [run(i, parent=1) for i in range(2, 30)]
    page = LeaderboardCache().groups(snapshot(specs), {}, "parent", group_key=v(1),
                                     offset=10, limit=5)
    assert page["key"] == v(1)
    assert members(page) == [v(i) for i in range(12, 17)]
    assert page["rows_total"] == 28
    assert page["target"]["verstr"] == v(1)


def test_an_unknown_group_key_is_a_lookup_error():
    with pytest.raises(LookupError):
        LeaderboardCache().groups(snapshot(FLEET), {}, "parent", group_key="nope")


@pytest.mark.parametrize("group", ["inputs", "params.", "tags", "metrics.loss", "PARENT"])
def test_an_unknown_group_field_is_rejected(group):
    with pytest.raises(ValueError):
        LeaderboardCache().groups(snapshot(FLEET), {}, group)


def test_an_unknown_aggregate_is_rejected():
    with pytest.raises(ValueError):
        LeaderboardCache().groups(snapshot(FLEET), {}, "parent", agg="sum")
