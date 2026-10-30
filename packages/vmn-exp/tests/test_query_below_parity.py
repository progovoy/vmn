"""The core's ``live_below``/``running_below``/``stuck_below``
(:mod:`vmn_exp.core.query_below`) and the UI board's (read from its job
rollups) agree on every job, generation after generation of a random fleet
— archiving, re-linking, starting and finishing runs — so the board's
``top_q`` and its printed ``vmn-exp list`` line cannot drift apart."""
import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_live_below import BELOW

from vmn_exp.core import status as status_mod
from vmn_exp.core.query import BELOW_FIELDS, filter_rows
from vmn_exp.core.query_below import below_extra


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _ui_counts(rollups, verstr):
    counts = (rollups.get(verstr) or {}).get("counts") or {}
    return {field: sum(counts.get(s, 0) for s in states) for field, states in BELOW.items()}


def _core_counts(extra, verstr):
    return {field: extra[field](verstr) for field in BELOW_FIELDS}


def _top(cache, snap, query):
    page = cache.page(snap, {}, limit=1000, top=True, top_query=query)
    return sorted(r["verstr"] for r in page["rows"])


def _core_top(rows, query):
    tops = [r for r in rows if not r["depth"] and not r.get("archived")]
    return sorted(r["verstr"] for r in filter_rows(tops, query, extra=below_extra(rows)))


@pytest.mark.parametrize("seed", range(4))
def test_core_and_board_count_the_same_runs_below(seed):
    fleet, cache = Fleet(seed), LeaderboardCache()
    fleet.seed(60, T0, sweeps=5, live=12)
    for _ in range(6):
        snap = fleet.snapshot()
        rows = cache.rows(snap, archived=True)
        extra, rollups = below_extra(rows), cache.job_rollups(snap, {})
        for row in rows:
            verstr = row["verstr"]
            assert _core_counts(extra, verstr) == _ui_counts(rollups, verstr), verstr
        for field in BELOW_FIELDS:
            assert _top(cache, snap, f"{field} > 0") == _core_top(rows, f"{field} > 0"), field
        fleet.mutate(T0, 15)


def test_a_query_without_them_never_counts(monkeypatch):
    import vmn_exp.core.query_below as query_below

    fleet = Fleet(1)
    fleet.seed(20, T0)
    rows = LeaderboardCache().rows(fleet.snapshot(), archived=True)
    monkeypatch.setattr(query_below, "below_counts", lambda rows: pytest.fail("counted"))
    assert filter_rows(rows, 'status = "running"', extra=below_extra(rows))
