"""Plan 28 N6: the tree's children pages, ``children_of=<v>``: the direct
children of a run, filtered, sorted and paged like the board, each with
children carrying its ``job`` summary (attention counted over its own
subtree, split counts when a split is given) and every row an ``open``
hint (attention or live runs below)."""
import pytest
from leaderboard_fleet import T0, Fleet, running
from vmn_exp.ui import leaderboard_cache as cache_mod
from vmn_exp.ui.attention import AttentionQuery
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_scope import UnknownScope

from vmn_exp.core import status as status_mod

SCHEMA = {"loss": {"goal": "min", "primary": True}}


@pytest.fixture
def tree(monkeypatch):
    """Launch L: D1 (3 ended), D2 (2 ended, 1 running), D3 (25 ended),
    D4 -> study S -> 3 ended (one of them ``bad``), and a leaf directly under
    L; a second launch L2 with 2 ended runs."""
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(5)
    end = lambda: fleet.ended(T0, code=0)  # noqa: E731
    launch = fleet.append(state=running(T0))
    d1, d2, d3, d4 = (fleet.append(parent=launch, state=end()) for _ in range(4))
    for _ in range(3):
        fleet.append(parent=d1, state=end())
    for _ in range(2):
        fleet.append(parent=d2, state=end())
    fleet.append(parent=d2, state=running(T0))
    for _ in range(25):
        fleet.append(parent=d3, state=end())
    study = fleet.append(parent=d4, state=end())
    leaves = [fleet.append(parent=study, state=end()) for _ in range(3)]
    leaf = fleet.append(parent=launch, state=end())
    other = fleet.append(state=end())
    for _ in range(2):
        fleet.append(parent=other, state=end())
    names = dict(launch=launch, d1=d1, d2=d2, d3=d3, d4=d4, study=study, bad=leaves[0],
                 leaf=leaf, other=other)
    return fleet, names, LeaderboardCache()


def _bad(names):
    return (AttentionQuery("bad", f'verstr = "{names["bad"]}"', "error"),)


def _children(cache, snap, parent, **params):
    params.setdefault("limit", 100)
    return cache.page(snap, SCHEMA, children_of=parent, **params)


def _by_verstr(page):
    return {row["verstr"]: row for row in page["rows"]}


def test_children_of_lists_the_direct_children_each_with_its_job(tree):
    fleet, n, cache = tree
    snap = fleet.snapshot()
    page = _children(cache, snap, n["launch"])
    rows = _by_verstr(page)
    assert set(rows) == {n["d1"], n["d2"], n["d3"], n["d4"], n["leaf"]}
    assert page["total"] == 5
    summaries = cache.job_rollups(snap, SCHEMA)
    for node in ("d1", "d2", "d3", "d4"):
        assert rows[n[node]]["job"]["total"] == summaries[n[node]]["total"]
    assert rows[n["d4"]]["job"]["total"] == 4  # the study and its 3 runs
    assert rows[n["leaf"]]["job"] is None
    assert all("duration_ratio" in row for row in rows.values())


def test_a_nested_node_lists_its_own_children(tree):
    fleet, n, cache = tree
    snap = fleet.snapshot()
    assert set(_by_verstr(_children(cache, snap, n["d4"]))) == {n["study"]}
    assert len(_children(cache, snap, n["study"])["rows"]) == 3
    assert _children(cache, snap, n["leaf"]) == {"rows": [], "total": 0, "next_cursor": None}


def test_a_node_counts_attention_over_its_own_subtree(tree):
    fleet, n, cache = tree
    snap = fleet.snapshot()
    attention = _bad(n)
    top = _by_verstr(_children(cache, snap, n["launch"], attention=attention))
    assert top[n["d4"]]["job"]["attention"] == {"bad": 1}
    assert top[n["d1"]]["job"]["attention"] == {"bad": 0}
    assert top[n["d4"]]["job"]["attention_rank"] > top[n["d1"]]["job"]["attention_rank"]
    mid = _by_verstr(_children(cache, snap, n["d4"], attention=attention))
    assert mid[n["study"]]["job"]["attention"] == {"bad": 1}
    leaves = _by_verstr(_children(cache, snap, n["study"], attention=attention))
    assert leaves[n["bad"]]["attention"] == {"bad": 1}
    assert sum("attention" in row for row in leaves.values()) == 1


def test_open_marks_nodes_with_attention_or_live_runs_below(tree):
    fleet, n, cache = tree
    snap = fleet.snapshot()
    rows = _by_verstr(_children(cache, snap, n["launch"], attention=_bad(n)))
    assert {v for v, row in rows.items() if row["open"]} == {n["d2"], n["d4"]}
    plain = _by_verstr(_children(cache, snap, n["launch"]))
    assert {v for v, row in plain.items() if row["open"]} == {n["d2"]}


def test_children_filter_and_sort_like_the_board(tree):
    fleet, n, cache = tree
    snap = fleet.snapshot()
    running_only = _children(cache, snap, n["d2"], status="running")
    assert running_only["total"] == 1
    by_total = _children(cache, snap, n["launch"], sort="job:total")["rows"]
    assert [row["verstr"] for row in by_total[:2]] == [n["d3"], n["d4"]]
    assert {row["verstr"] for row in by_total[2:4]} == {n["d1"], n["d2"]}
    assert by_total[-1]["verstr"] == n["leaf"]  # no job: last
    q = f'verstr in ("{n["d1"]}", "{n["leaf"]}")'
    assert set(_by_verstr(_children(cache, snap, n["launch"], query=q))) == {n["d1"], n["leaf"]}


def test_cursor_pages_walk_every_child_once(tree):
    fleet, n, cache = tree
    snap = fleet.snapshot()
    whole = [row["verstr"] for row in _children(cache, snap, n["d3"])["rows"]]
    seen, cursor = [], None
    while True:
        page = _children(cache, snap, n["d3"], limit=7, cursor=cursor)
        seen += [row["verstr"] for row in page["rows"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == whole and len(seen) == 25


def test_a_new_generation_moves_the_children_page(tree):
    fleet, n, cache = tree
    first = _children(cache, fleet.snapshot(), n["d1"])
    assert first["total"] == 3
    added = fleet.append(parent=n["d1"], state=running(T0))
    snap = fleet.snapshot()
    page = _children(cache, snap, n["d1"])
    assert page["total"] == 4 and added in _by_verstr(page)
    top = _by_verstr(_children(cache, snap, n["launch"]))
    assert top[n["d1"]]["open"] and top[n["d1"]]["job"]["total"] == 4


def test_children_orders_never_evict_the_boards(tree, monkeypatch):
    fleet, n, cache = tree
    snap = fleet.snapshot()
    cache.page(snap, SCHEMA, limit=50)
    builds = []
    real = cache_mod._Static.build.__func__

    def counted(cls, base, schema, f, slots=None):
        builds.append(f.children_of)
        return real(cls, base, schema, f, slots)

    monkeypatch.setattr(cache_mod._Static, "build", classmethod(counted))
    parents = [row["verstr"] for row in cache.rows(snap)]
    assert len(parents) * 2 > cache_mod.LATEST_ORDERS
    for parent in parents:
        for sort in (None, "loss"):
            _children(cache, snap, parent, sort=sort)
    snap = fleet.snapshot()
    for parent in parents[:5]:
        _children(cache, snap, parent)
    builds.clear()
    cache.page(snap, SCHEMA, limit=50)
    assert builds == []  # moved on, not rebuilt


def test_a_split_adds_each_child_jobs_counts_per_value(tree):
    fleet, n, cache = tree
    snap = fleet.snapshot()
    rows = _by_verstr(_children(cache, snap, n["launch"], split="params.opt"))
    job = rows[n["d3"]]["job"]
    assert job["split"] == "params.opt"
    assert job["by"] == cache.jobs.split_rollup(snap, "params.opt", n["d3"])
    assert sum(entry["total"] for entry in job["by"]) == 25
    assert rows[n["leaf"]]["job"] is None


def test_an_unknown_parent_is_refused(tree):
    fleet, _, cache = tree
    with pytest.raises(UnknownScope):
        _children(cache, fleet.snapshot(), "9.9.9-dev.nope")


def test_children_of_cannot_be_combined_with_top(tree):
    fleet, n, cache = tree
    with pytest.raises(ValueError):
        _children(cache, fleet.snapshot(), n["launch"], top=True)
