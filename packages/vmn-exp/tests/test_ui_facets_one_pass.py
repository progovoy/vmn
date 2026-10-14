"""The facets answer (``experiments-facets``) carries ``jobs``/``singles``
from the same walk of the filtered rows as the vocabulary, skips them under
a scope (a subtree has no top-level run), and is served by an ETag known
before anything is computed."""
import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod
from vmn_exp.ui import leaderboard_answers, leaderboard_cache


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = Fleet(5)
    jobs = fleet.seed_jobs(3, 10, T0, live=4)
    singles = [fleet.append(state=fleet.ended(T0)) for _ in range(6)]
    return fleet, jobs, singles


def _counting_tails(monkeypatch):
    walks = []
    real = leaderboard_cache._Base.tail

    def tail(self, bucket, count, f):
        walks.append(f)
        return real(self, bucket, count, f)

    monkeypatch.setattr(leaderboard_cache._Base, "tail", tail)
    return walks


def test_filtered_facets_walk_the_filtered_rows_once(board, monkeypatch):
    fleet, jobs, _ = board
    snap = fleet.snapshot()
    want = dict(LeaderboardCache().facets(snap, status="running"),
                **LeaderboardCache().top_counts(snap, status="running"))
    cache = LeaderboardCache()
    cache.page(snap, {}, limit=1)
    walks = _counting_tails(monkeypatch)

    got = cache.facets_payload(snap, status="running")

    assert got == want and (got["jobs"], got["singles"]) == (len(jobs), 0)
    assert len(walks) == 1


def test_scoped_facets_count_no_top_level_runs(board, monkeypatch):
    fleet, jobs, _ = board
    snap = fleet.snapshot()

    def boom(rows):
        raise AssertionError("top counts walked under a scope")

    monkeypatch.setattr(leaderboard_answers, "top_counts", boom)
    got = LeaderboardCache().facets_payload(snap, scope=jobs[0])

    assert (got["jobs"], got["singles"]) == (0, 0) and got["total"] == 10


def test_unfiltered_facets_carry_the_app_top_counts(board):
    fleet, jobs, singles = board
    got = LeaderboardCache().facets_payload(fleet.snapshot())
    assert (got["jobs"], got["singles"]) == (len(jobs), len(singles))


def test_a_repeated_facets_request_is_a_304_without_computing(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from test_ui_leaderboard_groups_route import _client, _record
    from test_ui_scope_route import BASE

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)

    _record(str(root), 1, 0.5)
    _record(str(root), 2, 0.7, 1)
    client = _client(tmp_path, str(root))
    for params in ({}, {"status": "succeeded"}):
        first = client.get(f"{BASE}/experiments-facets", params=params)
        assert first.status_code == 200 and "jobs" in first.json()
        calls = []
        for name in ("facets", "top_counts", "facets_payload"):
            real = getattr(LeaderboardCache, name, None)
            if real is not None:
                monkeypatch.setattr(LeaderboardCache, name,
                                    lambda *a, _r=real, _c=calls, **k: _c.append(1) or _r(*a, **k))
        again = client.get(f"{BASE}/experiments-facets", params=params,
                           headers={"If-None-Match": first.headers["etag"]})
        assert again.status_code == 304 and not calls
        monkeypatch.undo()
