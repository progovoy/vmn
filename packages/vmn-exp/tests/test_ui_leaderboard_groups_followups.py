"""Plan 22 §6 F1/F3/F4/F6 on the grouped leaderboard: each group's size
before the filter (``rows_unfiltered``), the aggregate the page was sorted by
(``aggregate``), the running rows across groups (``running``) and a no-value
group whose key no value can take."""
import pytest
from leaderboard_group_rows import group_of, keys, members, run, snapshot, v
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_group_fields import NONE

FLEET = [
    run(1), run(2, parent=1, metrics={"loss": 1.0}), run(3, parent=1, state="running"),
    run(4, parent=1, state="failed", metrics={"loss": 3.0}),
    run(5), run(6, parent=5, metrics={"loss": 2.0}),
    run(7, parent=5, archived=True),
]


def _groups(specs, group, cache=None, **params):
    return (cache or LeaderboardCache()).groups(snapshot(specs), {}, group, **params)


def _unfiltered(payload):
    return {g["key"]: (g["rows_total"], g["rows_unfiltered"]) for g in payload["groups"]}


def test_without_a_filter_a_groups_unfiltered_size_is_its_size():
    out = _groups(FLEET, "parent")
    assert _unfiltered(out) == {v(1): (3, 3), v(5): (1, 1)}  # runs 1 and 5 are headers


@pytest.mark.parametrize("params", [
    dict(status="succeeded"), dict(query="metrics.loss < 2.5"),
    dict(status="succeeded,failed", query="metrics.loss > 0"),
])
def test_a_filter_cuts_the_rows_but_not_the_unfiltered_size(params):
    out = _groups(FLEET, "parent", **params)
    assert _unfiltered(out)[v(1)][1] == 3
    assert _unfiltered(out)[v(1)][0] < 3


def test_the_unfiltered_size_keeps_the_archived_setting():
    hidden = _groups(FLEET, "parent", status="succeeded")
    shown = _groups(FLEET, "parent", status="succeeded", archived=True)
    assert _unfiltered(hidden)[v(5)] == (1, 1)
    assert _unfiltered(shown)[v(5)] == (2, 2)


def test_one_groups_rows_page_carries_its_unfiltered_size():
    one = _groups(FLEET, "parent", status="failed", group_key=v(1))
    assert (one["rows_total"], one["rows_unfiltered"]) == (1, 3)


def test_a_comments_like_rows_filter_keeps_the_unfiltered_size():
    out = LeaderboardCache().groups(
        snapshot(FLEET), {}, "parent",
        rows_filter=lambda rows: [r for r in rows if r["verstr"] == v(2)])
    assert _unfiltered(out) == {v(1): (1, 3)}


def test_the_unfiltered_size_follows_new_generations():
    cache = LeaderboardCache()
    _groups(FLEET, "parent", cache, status="succeeded")
    grown = FLEET + [run(8, parent=1, state="failed")]
    out = cache.groups(snapshot(grown, generation=2), {}, "parent", status="succeeded")
    assert _unfiltered(out)[v(1)] == (1, 4)


@pytest.mark.parametrize("agg", ["mean", "best", "median", "min", "max"])
def test_the_page_names_the_aggregate_it_was_sorted_by(agg):
    assert _groups(FLEET, "parent", agg=agg)["aggregate"] == agg


def test_the_page_counts_the_running_rows_of_every_group():
    assert _groups(FLEET, "parent")["running"] == 1
    assert _groups(FLEET, "parent", limit=1, rows_per_group=1)["running"] == 1
    assert _groups(FLEET, "parent", status="succeeded")["running"] == 0


def test_runs_are_counted_once_when_a_target_is_also_a_member():
    specs = [run(1, state="running"), run(2, rerun_of=1, state="running")]
    assert _groups(specs, "rerun_of")["running"] == 2


# -- F6: the no-value group's key -------------------------------------------
@pytest.mark.parametrize("field, value", [
    ("params.opt", "(none)"), ("tags.team", "(none)"), ("params.opt", NONE),
    ("tags.team", NONE + "x"), ("branch", "(none)"), ("branch", NONE),
])
def test_a_value_spelled_like_no_value_has_its_own_group(field, value):
    prefix, _, name = field.partition(".")
    with_value = {"branch": value} if prefix == "branch" else {prefix: {name: value}}
    # The fixture puts runs on main unless told otherwise.
    without = {"branch": None} if prefix == "branch" else {}
    out = _groups([run(1, **with_value), run(2, **without)], field)
    assert len(out["groups"]) == 2
    assert keys(out)[-1] == NONE
    assert members(group_of(out, NONE)) == [v(2)]
    valued = out["groups"][0]
    assert members(valued) == [v(1)]
    assert valued["label"] == f"{field} = {value}"
    assert group_of(out, NONE)["label"] == "(none)"


def test_the_no_value_key_is_none_of_the_labels():
    out = _groups([run(1), run(2, parent=1), run(3)], "parent")
    assert NONE not in ("(none)", "")
    assert group_of(out, NONE)["label"] == "(none)"


def test_a_value_group_and_the_no_value_group_page_apart():
    specs = [run(1, params={"opt": "(none)"}), run(2, params={"opt": "(none)"}), run(3)]
    page = _groups(specs, "params.opt", group_key="(none)", limit=10)
    assert members(page) == [v(1), v(2)]
    assert members(_groups(specs, "params.opt", group_key=NONE)) == [v(3)]


def test_a_link_spelled_like_no_value_is_a_missing_target():
    out = _groups([run(1, parent=NONE), run(2)], "parent")
    assert len(out["groups"]) == 2
    assert group_of(out, NONE)["label"] == "(none)"
    assert members(group_of(out, NONE)) == [v(2)]
    assert out["groups"][0]["label"] == f"{NONE} (not found)"
