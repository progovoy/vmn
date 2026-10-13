"""Plan 22 §6 F12: grouped by a link (``parent``, ``forked_from``,
``rerun_of``), the runs with no link are not a group. The no-link group is
marked ``loose`` and holds only the runs that head no group of the grouping
(those are shown as headers); field groupings and ``code_verstr`` keep a
plain ``(none)`` group."""
import pytest
from leaderboard_group_rows import group_of, keys, members, run, snapshot, v
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_group_fields import NONE

LINKS = ["parent", "forked_from", "rerun_of"]


def _groups(specs, group, schema=None, **params):
    return LeaderboardCache().groups(snapshot(specs, schema=schema), schema or {}, group, **params)


def _fleet(link):
    # Runs 1 and 4 head groups; 6 and 7 are linked to nothing and head nothing.
    return [run(1, metrics={"loss": 100.0}), run(2, metrics={"loss": 1.0}, **{link: 1}),
            run(3, **{link: 1}), run(4, state="running", metrics={"loss": 200.0}),
            run(5, **{link: 4}), run(6, metrics={"loss": 2.0}), run(7, state="fail")]


@pytest.mark.parametrize("link", LINKS)
def test_the_loose_rows_leave_out_the_runs_shown_as_headers(link):
    out = _groups(_fleet(link), link)
    assert keys(out) == [v(1), v(4), NONE]
    loose = group_of(out, NONE)
    assert loose["loose"] is True
    assert members(loose) == [v(6), v(7)]
    assert loose["rows_total"] == loose["rows_unfiltered"] == 2


@pytest.mark.parametrize("link", LINKS)
def test_the_loose_counts_and_aggregates_cover_the_loose_rows_only(link):
    loose = group_of(_groups(_fleet(link), link), NONE)
    assert loose["counts"] == {"total": 2, "running": 0, "waiting": 0, "done": 1,
                               "failed": 1, "stuck": 0}
    assert loose["aggregates"]["loss"]["n"] == 1
    assert loose["aggregates"]["loss"]["max"] == 2.0


@pytest.mark.parametrize("link", LINKS)
def test_the_board_totals_still_count_every_run(link):
    out = _groups(_fleet(link), link)
    assert out["total_rows"] == 7
    assert out["running"] == 1  # run 4, a header
    assert out["total_groups"] == 3


def test_no_loose_rows_means_no_loose_group():
    out = _groups([run(1), run(2, parent=1), run(3, parent=2)], "parent")
    assert keys(out) == [v(1), v(2)]
    assert out["total_groups"] == 2
    assert out["total_rows"] == 3
    with pytest.raises(LookupError):
        _groups([run(1), run(2, parent=1)], "parent", group_key=NONE)


def test_a_run_whose_group_a_filter_cut_is_a_loose_row():
    specs = [run(1, metrics={"loss": 1.0}), run(2, parent=1, metrics={"loss": 9.0}),
             run(3, metrics={"loss": 2.0}), run(4, parent=3, metrics={"loss": 3.0})]
    out = _groups(specs, "parent", query="metrics.loss < 5")
    assert keys(out) == [v(3), NONE]
    assert members(group_of(out, NONE)) == [v(1)]


@pytest.mark.parametrize("sort", [None, "loss", "timestamp", "c:total"])
def test_group_key_pages_the_loose_rows_around_the_headers(sort):
    specs = []
    for n in range(1, 31):
        specs.append(run(n, metrics={"loss": float(n)}, **({"parent": n - 1} if n % 5 == 0 else {})))
    # Runs 4, 9, 14 ... head a group of one (5, 10, 15 ...); the rest are loose.
    whole = _groups(specs, "parent", sort=sort, rows_per_group=100)
    loose = members(group_of(whole, NONE))
    assert len(loose) == 30 - 6 - 6
    assert not set(loose) & {v(n) for n in range(4, 30, 5)}
    for offset in (0, 3, 7, 17):
        page = _groups(specs, "parent", sort=sort, group_key=NONE, offset=offset, limit=4)
        assert members(page) == loose[offset:offset + 4]
        assert page["rows_total"] == len(loose)
        assert page["loose"] is True


@pytest.mark.parametrize("group,specs", [
    ("code_verstr", [run(1, code_verstr="0.1.0-dev.a.b"), run(2)]),
    ("branch", [run(1), run(2, branch=None)]),
    ("params.lr", [run(1, params={"lr": 0.1}), run(2)]),
    ("status", [run(1), run(2, state=None)]),
])
def test_other_groupings_keep_a_none_group_that_is_not_loose(group, specs):
    out = _groups(specs, group)
    assert all(g["loose"] is False for g in out["groups"])
    if NONE in keys(out):
        assert group_of(out, NONE)["label"] == "(none)"


def test_a_link_group_with_a_header_is_not_loose():
    out = _groups(_fleet("parent"), "parent")
    assert [g["loose"] for g in out["groups"]] == [False, False, True]


def test_the_loose_group_is_labelled_none():
    assert group_of(_groups(_fleet("parent"), "parent"), NONE)["label"] == "(none)"
