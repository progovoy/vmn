"""A ``verstr in (...)`` clause (the web client's row refresh) is answered
from the storage positions: the board filters only the named runs instead
of the whole app, and what matches never changes."""
import pytest
from leaderboard_fleet import T0
from test_ui_search_index_query import SCHEMA, _expected, _fleet
from vmn_exp.core import status as status_mod
from vmn_exp.ui import leaderboard_cache
from vmn_exp.ui.leaderboard_cache import LeaderboardCache


@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _in(verstrs):
    return "verstr in (" + ", ".join(f'"{v}"' for v in verstrs) + ")"


def test_a_verstr_list_filters_only_the_named_runs(monkeypatch):
    snap = _fleet(0).snapshot()
    named = [snap.rows[i]["verstr"] for i in (3, 150, 399)]
    cache = LeaderboardCache()
    cache.page(snap, SCHEMA, limit=50)
    sizes = []
    real = leaderboard_cache.filtered
    monkeypatch.setattr(leaderboard_cache, "filtered",
                        lambda s, rows, f: sizes.append(len(rows)) or real(s, rows, f))

    page = cache.page(snap, SCHEMA, query=_in(named + ["0.0.1-dev.gone"]), limit=50)

    assert {r["verstr"] for r in page["rows"]} == set(named) - {
        r["verstr"] for r in snap.rows if r.get("archived")}
    assert sizes and max(sizes) <= 20


@pytest.mark.parametrize("seed", range(2))
def test_verstr_lists_in_any_query_match_the_plain_filter(seed):
    fleet = _fleet(seed)
    cache = LeaderboardCache()
    for step in range(3):
        snap = fleet.snapshot()
        named = _in([snap.rows[i]["verstr"] for i in range(0, len(snap.rows), 37)])
        for query in [named, f"metrics.loss < 0.5 and {named}", f'name ~ "grid" or {named}',
                      f"not {named}", named.replace(" in ", " not in ", 1),
                      f"{named} or metrics.loss > 0.9", 'verstr in ("x", 3)']:
            for sort in (None, "loss"):
                page = cache.page(snap, SCHEMA, query=query, sort=sort, limit=1000)
                assert [r["verstr"] for r in page["rows"]] == _expected(snap, query, sort), query
        fleet.mutate(T0, 10, removals=step == 1)
