"""Plan 28 N1 on the board: ``group=up.params.<k>`` (and ``up.tags.<k>``,
``up(<field> = <value>).<field>``) groups runs by an ancestor's value, chart
columns read it, and orders and groupings moved across generations follow an
ancestor whose value changed."""
import pytest
from leaderboard_fleet import T0, Fleet, finished
from leaderboard_group_rows import run, snapshot, v
from vmn_exp.core import status as status_mod
from vmn_exp.core.query import filter_rows
from vmn_exp.core.query_extra import lean_extra
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui import leaderboard_groups as groups_mod
from vmn_exp.ui.leaderboard_group_fields import NONE, check_group

SCHEMA = {}


def _tree():
    return snapshot([
        run(1, params={"date": "d1"}, tags={"kind": "date"}),
        run(2, parent=1, params={"group": "g1"}, tags={"kind": "study"}),
        run(3, parent=2), run(4, parent=2),
        run(5, params={"date": "d2"}, tags={"kind": "date"}),
        run(6, parent=5, params={"group": "g2"}, tags={"kind": "study"}),
        run(7, parent=6),
        run(8),
    ])


def _groups(snap, group, cache=None, **params):
    out = (cache or lb.LeaderboardCache()).groups(snap, SCHEMA, group, rows_per_group=100,
                                                  limit=100, **params)
    return {g["key"]: g for g in out["groups"]}


def _members(groups):
    return {key: sorted(r["verstr"] for r in g["rows"]) for key, g in groups.items()}


@pytest.mark.parametrize("group", ["up.params.date", "up.tags.kind", "up.name",
                                   'up(tags.kind = "study").params.group',
                                   'up.params."odd key"'])
def test_up_fields_are_group_fields(group):
    assert check_group(group) == group


@pytest.mark.parametrize("group", ["up.status", "up.params", "up(tags.kind = 'x')",
                                   "up(kind = 'outer').params.g", "up.metrics.loss"])
def test_other_up_fields_are_refused(group):
    with pytest.raises(ValueError):
        check_group(group)


def test_grouped_by_an_ancestor_param():
    groups = _groups(_tree(), "up.params.date")
    assert _members(groups) == {"d1": [v(2), v(3), v(4)], "d2": [v(6), v(7)],
                                NONE: [v(1), v(5), v(8)]}
    assert groups["d1"]["label"] == "up.params.date = d1"
    assert groups["d1"]["clause"] == 'up.params.date = "d1"'
    assert groups[NONE]["clause"] == "up.params.date = null"


def test_grouped_by_a_selected_ancestor():
    group = 'up(tags.kind = "study").params.group'
    groups = _groups(_tree(), group)
    assert _members(groups) == {"g1": [v(3), v(4)], "g2": [v(7)],
                                NONE: [v(1), v(2), v(5), v(6), v(8)]}
    assert groups["g2"]["clause"] == f'{group} = "g2"'


def test_each_group_clause_selects_its_rows():
    snap = _tree()
    for group in ("up.params.date", 'up(tags.kind = "date").params.date'):
        for key, g in _groups(snap, group).items():
            kept = filter_rows(list(snap.rows), g["clause"], extra=lean_extra(snap))
            assert sorted(r["verstr"] for r in kept) == sorted(r["verstr"] for r in g["rows"])


def test_grouped_with_a_query_and_a_status():
    groups = _groups(_tree(), "up.params.date", query='up.params.group = "g1"')
    assert _members(groups) == {"d1": [v(3), v(4)]}


def test_chart_columns_read_ancestor_values():
    snap = _tree()
    out = lb.LeaderboardCache().columns(snap, SCHEMA, ["group:up.params.date", "up.params.date"])
    by_verstr = dict(zip(out["verstrs"], out["columns"]["group:up.params.date"]))
    assert by_verstr[v(3)] == "d1" and by_verstr[v(8)] == NONE
    values = dict(zip(out["verstrs"], out["columns"]["up.params.date"]))
    assert values[v(7)] == "d2" and values[v(1)] is None


class _Builds:
    """Counts orders and groupings built from every row."""

    def __init__(self, monkeypatch):
        self.calls = 0
        for owner in (groups_mod.Grouping, lb._Static):
            real = owner.build

            def counted(*args, _real=real, **kwargs):
                self.calls += 1
                return _real(*args, **kwargs)

            monkeypatch.setattr(owner, "build", staticmethod(counted))


def _fleet():
    fleet = Fleet(1)
    root = fleet.append(state=finished())
    mid = fleet.append(parent=root, state=finished())
    for _ in range(6):
        fleet.append(parent=mid, state=finished())
    for _ in range(200):
        fleet.append(state=finished())
    return fleet


def _answers(cache, snap):
    group = cache.groups(snap, SCHEMA, "up.params.opt", rows_per_group=100, limit=100)
    page = cache.page(snap, SCHEMA, query='up.params.opt = "lion"')
    return group, [r["verstr"] for r in page]


def test_an_ancestor_whose_value_changes_moves_the_runs_below_it(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = _fleet()
    cache = lb.LeaderboardCache(bucket_sec=2, size=256)
    _answers(cache, fleet.snapshot())
    for i, opt in ((1, "lion"), (0, "tiger"), (1, "adam")):
        fleet.edit(i, opt=opt)
        snap = fleet.snapshot()
        assert _answers(cache, snap) == _answers(lb.LeaderboardCache(bucket_sec=2), snap)
    assert _answers(cache, snap)[1] == []


def test_other_changes_move_orders_on_without_a_rebuild(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = _fleet()
    cache = lb.LeaderboardCache(bucket_sec=2, size=256)
    fleet.edit(1, opt="lion")
    _answers(cache, fleet.snapshot())
    fleet.edit(5, values={"loss": 0.1})  # a leaf
    fleet.edit(20, opt="sgd")  # a run with no children
    fleet.edit(1, values={"loss": 0.2})  # the parent, its params unchanged
    snap = fleet.snapshot()
    builds = _Builds(monkeypatch)
    mine = _answers(cache, snap)
    assert builds.calls == 0
    assert mine == _answers(lb.LeaderboardCache(bucket_sec=2), snap)
