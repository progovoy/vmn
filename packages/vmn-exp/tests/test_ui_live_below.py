"""Plan 28 §4.5: ``live_below``, a top-level row's runs below it still
running, waiting or stuck (its Jobs view rollup's counts), readable by
``top_query`` — so the Live preset keeps a container outer run whose
``tree_status`` reads ``failed`` while the rest of its runs still run."""
import pytest
from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod

SCHEMA = {"loss": {"goal": "min", "primary": True}}
# The web's presets (webui/src/pages/Experiments/presets.ts).
IN_FLIGHT = ('status in ("running", "stuck") or tree_status in ("running", "created", "stuck")'
             ' or live_below > 0')
LIVE_QUERY = f'{IN_FLIGHT} or finished_at >= ago("6h")'
REVIEW_QUERY = f"not ({IN_FLIGHT})"


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(7)
    container = fleet.append()  # never ran itself: own status created
    failed = fleet.append(parent=container, state=finished(1))
    live = fleet.append(parent=container, state=running(T0))
    done = fleet.append(state=finished(0))
    old_done = fleet.append()
    fleet.append(parent=old_done, state=finished(0))
    return fleet, (container, failed, live, done, old_done), LeaderboardCache()


def _top(cache, snap, top_query, **params):
    page = cache.page(snap, SCHEMA, limit=100, top=True, top_query=top_query, **params)
    return {r["verstr"] for r in page["rows"]}


def test_a_container_with_a_failed_and_a_running_run_is_in_flight(board):
    fleet, (container, *_), cache = board
    snap = fleet.snapshot()
    rows = {r["verstr"]: r for r in cache.page(snap, SCHEMA, limit=100, top=True)["rows"]}
    assert rows[container]["tree_status"] == "failed"
    assert container in _top(cache, snap, LIVE_QUERY)
    assert container not in _top(cache, snap, REVIEW_QUERY)


def test_an_ended_tree_is_in_review(board):
    fleet, (container, failed, live, done, old_done), cache = board
    assert {done, old_done} <= _top(cache, fleet.snapshot(), REVIEW_QUERY)
    assert _top(cache, fleet.snapshot(), "live_below = 0") == {done, old_done}


def test_live_below_follows_a_new_generation(board):
    fleet, (container, failed, live, *_), cache = board
    assert container in _top(cache, fleet.snapshot(), "live_below > 0")
    fleet.set_state(fleet.index(live), finished(0))
    snap = fleet.snapshot()
    assert container not in _top(cache, snap, "live_below > 0")
    assert container in _top(cache, snap, REVIEW_QUERY)


def test_live_below_with_a_job_sort_and_a_cursor(board):
    fleet, (container, *_), cache = board
    snap = fleet.snapshot()
    page = cache.page(snap, SCHEMA, limit=1, top=True, top_query="live_below > 0",
                      sort="job:attention")
    assert [r["verstr"] for r in page["rows"]] == [container]
    assert page["total"] == 1


def test_grouped_live_below(board):
    fleet, (container, *_), cache = board
    body = cache.groups(fleet.snapshot(), SCHEMA, "status", top=True, top_query="live_below > 0")
    assert {r["verstr"] for g in body["groups"] for r in g["rows"]} == {container}


def test_grouped_live_below_with_a_query_counts_the_unfiltered_group(board):
    fleet, (container, *_), cache = board
    body = cache.groups(fleet.snapshot(), SCHEMA, "status", top=True,
                        top_query="live_below > 0", query=f'verstr != "{container}"')
    assert [r for g in body["groups"] for r in g["rows"]] == []


def test_columns_keep_the_top_query(board):
    fleet, (container, *_), cache = board
    cols = cache.columns(fleet.snapshot(), SCHEMA, [], limit=100, top=True,
                         top_query="live_below > 0")
    assert cols["verstrs"] == [container]
    assert cols["total"] == 1
