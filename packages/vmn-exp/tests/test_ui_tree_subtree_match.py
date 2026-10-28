"""Plan 28 N6 follow-up: a tree page's filters over subtrees,
``children_of=<v>&match_subtree=1``: a child is kept when it or any run
below it passes the status filter and the query, carrying ``matched`` (its
subtree's passing runs, itself included) and opening when a run below it
passes; the kept children keep the board's order and cursor paging."""
from leaderboard_fleet import T0, running
from test_ui_tree_children import SCHEMA, tree  # noqa: F401 (the fixture)


def _children(cache, snap, parent, **params):
    params.setdefault("limit", 100)
    return cache.page(snap, SCHEMA, children_of=parent, match_subtree=True, **params)


def _by_verstr(page):
    return {row["verstr"]: row for row in page["rows"]}


def test_a_status_keeps_the_children_whose_subtree_holds_one(tree):  # noqa: F811
    fleet, n, cache = tree
    snap = fleet.snapshot()
    assert cache.page(snap, SCHEMA, children_of=n["launch"], status="running",
                      limit=100)["total"] == 0  # the children's own status
    page = _children(cache, snap, n["launch"], status="running")
    rows = _by_verstr(page)
    assert set(rows) == {n["d2"]} and page["total"] == 1
    assert rows[n["d2"]]["matched"] == 1 and rows[n["d2"]]["open"]
    assert rows[n["d2"]]["job"]["total"] == 3


def test_a_query_leads_down_to_the_matching_leaf(tree):  # noqa: F811
    fleet, n, cache = tree
    snap = fleet.snapshot()
    q = f'verstr = "{n["bad"]}"'
    top = _by_verstr(_children(cache, snap, n["launch"], query=q))
    assert set(top) == {n["d4"]} and top[n["d4"]]["open"]
    mid = _by_verstr(_children(cache, snap, n["d4"], query=q))
    assert set(mid) == {n["study"]} and mid[n["study"]]["matched"] == 1
    leaves = _by_verstr(_children(cache, snap, n["study"], query=q))
    assert set(leaves) == {n["bad"]}
    assert leaves[n["bad"]]["matched"] == 1 and not leaves[n["bad"]]["open"]


def test_a_child_matching_only_itself_stays_folded(tree):  # noqa: F811
    fleet, n, cache = tree
    snap = fleet.snapshot()
    q = f'verstr in ("{n["d1"]}", "{n["leaf"]}")'
    rows = _by_verstr(_children(cache, snap, n["launch"], query=q))
    assert set(rows) == {n["d1"], n["leaf"]}
    assert not rows[n["d1"]]["open"] and rows[n["d1"]]["matched"] == 1


def test_without_filters_it_is_the_plain_page(tree):  # noqa: F811
    fleet, n, cache = tree
    snap = fleet.snapshot()
    plain = cache.page(snap, SCHEMA, children_of=n["launch"], limit=100)
    assert _children(cache, snap, n["launch"]) == plain


def test_kept_children_keep_the_order_and_page_by_cursor(tree):  # noqa: F811
    fleet, n, cache = tree
    snap = fleet.snapshot()
    whole = [row["verstr"] for row in
             _children(cache, snap, n["launch"], status="succeeded", sort="job:total")["rows"]]
    assert len(whole) == 5 and whole[:2] == [n["d3"], n["d4"]]
    seen, cursor = [], None
    while True:
        page = _children(cache, snap, n["launch"], status="succeeded", sort="job:total",
                         limit=2, cursor=cursor)
        seen += [row["verstr"] for row in page["rows"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == whole


def test_a_new_generation_moves_the_matches(tree):  # noqa: F811
    fleet, n, cache = tree
    assert set(_by_verstr(_children(cache, fleet.snapshot(), n["launch"],
                                    status="running"))) == {n["d2"]}
    fleet.append(parent=n["d1"], state=running(T0))
    rows = _by_verstr(_children(cache, fleet.snapshot(), n["launch"], status="running"))
    assert set(rows) == {n["d1"], n["d2"]}
