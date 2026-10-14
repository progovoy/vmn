"""Plan 23 S8b: the Jobs view's search over every run. With ``match_subtree``
a top-level row is kept when it or any run of its subtree passes ``q``; it
carries ``matched`` (how many runs of its tree pass), and the page carries
``jobs_matched`` and ``runs_matched`` (every passing run of the app)."""
import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.core import status as status_mod
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMA = {"loss": {"goal": "min", "primary": True}}


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(3)
    jobs = fleet.seed_jobs(3, 10, T0, live=4)
    hits = [fleet.append(parent=jobs[0], state=fleet.ended(T0), verstr=f"1.0.0-dev.needle{i}")
            for i in range(3)]
    nested = fleet.append(parent=jobs[1])
    deep = fleet.append(parent=nested, state=fleet.ended(T0), verstr="1.0.0-dev.needle-deep")
    single = fleet.append(state=fleet.ended(T0), verstr="1.0.0-dev.needle-single")
    others = [fleet.append(state=fleet.ended(T0)) for _ in range(3)]
    return fleet, jobs, hits, deep, single, others, LeaderboardCache()


def _page(cache, snap, **params):
    return cache.page(snap, SCHEMA, limit=100, top=True, match_subtree=True, **params)


NEEDLE = 'verstr ~ "needle"'


def test_a_job_with_matching_runs_is_kept_with_their_count(board):
    fleet, jobs, hits, deep, single, others, cache = board
    page = _page(cache, fleet.snapshot(), query=NEEDLE)
    rows = {r["verstr"]: r for r in page["rows"]}
    assert set(rows) == {jobs[0], jobs[1], single}
    assert rows[jobs[0]]["matched"] == 3
    assert rows[jobs[1]]["matched"] == 1  # the nested job's run counts for the top job
    assert rows[single]["matched"] == 1
    assert rows[jobs[0]]["job"]["total"] == 13
    assert (page["total"], page["jobs_matched"], page["runs_matched"]) == (3, 3, 5)


def test_a_job_matching_itself_counts_itself(board):
    fleet, jobs, *_, cache = board
    page = _page(cache, fleet.snapshot(), query=f'verstr = "{jobs[2]}"')
    assert [(r["verstr"], r["matched"]) for r in page["rows"]] == [(jobs[2], 1)]
    assert page["runs_matched"] == 1


def test_rows_keep_the_jobs_view_order(board):
    fleet, *_, cache = board
    snap = fleet.snapshot()
    order = [r["verstr"] for r in cache.page(snap, SCHEMA, limit=100, top=True)["rows"]]
    kept = [r["verstr"] for r in _page(cache, snap, query=NEEDLE)["rows"]]
    assert kept == [v for v in order if v in kept]


def test_status_filters_the_top_rows_not_the_matching_runs(board):
    fleet, jobs, hits, deep, single, others, cache = board
    page = _page(cache, fleet.snapshot(), query=NEEDLE, status="running")
    assert {r["verstr"] for r in page["rows"]} == {jobs[0], jobs[1]}
    assert page["runs_matched"] == 5


def test_archived_runs_match_only_with_archived(board):
    fleet, jobs, hits, *_, cache = board
    for verstr in hits:
        fleet.edit(fleet.index(verstr), archived=True)
    snap = fleet.snapshot()
    assert jobs[0] not in {r["verstr"] for r in _page(cache, snap, query=NEEDLE)["rows"]}
    rows = {r["verstr"]: r for r in _page(cache, snap, query=NEEDLE, archived=True)["rows"]}
    assert rows[jobs[0]]["matched"] == 3


def test_a_new_generation_moves_the_counts(board):
    fleet, jobs, *_, cache = board
    _page(cache, fleet.snapshot(), query=NEEDLE)
    fleet.append(parent=jobs[2], state=fleet.ended(T0), verstr="1.0.0-dev.needle-late")
    page = _page(cache, fleet.snapshot(), query=NEEDLE)
    assert {r["verstr"]: r["matched"] for r in page["rows"]}[jobs[2]] == 1
    assert page["runs_matched"] == 6


def test_paging_keeps_the_totals(board):
    fleet, *_, cache = board
    page = cache.page(fleet.snapshot(), SCHEMA, limit=1, offset=1, top=True,
                      match_subtree=True, query=NEEDLE)
    assert len(page["rows"]) == 1
    assert (page["total"], page["jobs_matched"], page["runs_matched"]) == (3, 3, 5)


def test_without_match_subtree_q_reads_the_top_rows_own_fields(board):
    fleet, jobs, hits, deep, single, others, cache = board
    page = cache.page(fleet.snapshot(), SCHEMA, limit=100, top=True, query=NEEDLE)
    assert [r["verstr"] for r in page["rows"]] == [single]
    assert "matched" not in page["rows"][0] and "runs_matched" not in page


def test_match_subtree_without_a_query_is_the_plain_jobs_view(board):
    fleet, *_, cache = board
    snap = fleet.snapshot()
    plain = cache.page(snap, SCHEMA, limit=100, top=True)
    assert _page(cache, snap) == plain


def test_match_subtree_needs_top(board):
    fleet, *_, cache = board
    with pytest.raises(ValueError):
        cache.page(fleet.snapshot(), SCHEMA, limit=10, match_subtree=True, query=NEEDLE)
