"""Plan 23 S8: the leaderboard answers ``~`` clauses on indexed fields from
the search index's candidates, verified by the query matcher — so a page is
exactly what the plain filter-and-sort answers, generation after generation."""
import pytest
from leaderboard_fleet import T0
from search_fleet import TextFleet
from vmn_exp.core import status as status_mod
from vmn_exp.core.query import parse_query
from vmn_exp.core.tree import annotate_rows
from vmn_exp.ui import search_prefilter
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.readers.experiments import apply_filters, sort_rows
from vmn_exp.ui.search_index import SearchIndex

SCHEMA = {"loss": {"goal": "min"}}
QUERIES = [
    'name ~ "grid" or verstr ~ "grid" or note ~ "grid" or branch ~ "grid"',
    'name ~ "t1"',
    'note ~ "beta" and metrics.loss < 0.5',
    'tags ~ "sweep" or command ~ "alpha"',
    'tags.lr ~ "a"',
    'params.model ~ "ab" and not name ~ "x"',
    'error_summary ~ "runtimeerror"',
    'author contains "BOB"',
    'name ~ "a" or metrics.loss > 0.9',
    'not note ~ "grid"',
    'verstr ~ "dev.r0001" and (branch ~ "b1" or name ~ "lr")',
    'name ~ ""',
    'name !~ "grid"',
]


def _expected(snap, query, sort=None):
    rows = [r for r in annotate_rows(snap.rows, snap.run_states, snap.run_state_observed_at)
            if not r.get("archived")]
    return [r["verstr"] for r in sort_rows(apply_filters(rows, query=query), SCHEMA, sort=sort)]


@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _fleet(seed):
    fleet = TextFleet(seed)
    fleet.seed(400, T0, sweeps=5, live=10)
    return fleet


def test_candidates_cover_only_clauses_the_index_can_answer():
    index = SearchIndex.build(_fleet(0).snapshot())
    found = lambda q: search_prefilter.candidates(parse_query(q), index)  # noqa: E731
    assert found('name ~ "grid"') == set(index.find("grid", ["name"]))
    assert found('name ~ "grid" and metrics.loss < 1') == set(index.find("grid", ["name"]))
    assert found('name ~ "grid" or note ~ "lr"') == (
        set(index.find("grid", ["name"])) | set(index.find("lr", ["note"])))
    for query in ['name ~ "grid" or metrics.loss < 1', 'not name ~ "grid"', 'name !~ "a"',
                  'name = "grid"', 'name ~ ""', 'status ~ "run"', 'name ~ "a\x02"']:
        assert found(query) is None, query


@pytest.mark.parametrize("seed", range(3))
def test_pages_with_a_text_clause_match_the_plain_filter(seed):
    fleet = _fleet(seed)
    cache = LeaderboardCache()
    for step in range(6):
        snap = fleet.snapshot()
        for query in QUERIES:
            for sort in (None, "loss"):
                page = cache.page(snap, SCHEMA, query=query, sort=sort, limit=1000)
                assert [r["verstr"] for r in page["rows"]] == _expected(snap, query, sort), query
        fleet.mutate(T0, 10, removals=step == 3)
        fleet.mutate_text(5)


def test_the_index_answers_the_text_clause(monkeypatch):
    snap = _fleet(1).snapshot()
    cache = LeaderboardCache()
    cache.page(snap, SCHEMA, limit=50)
    seen = []
    real = search_prefilter.candidates
    monkeypatch.setattr(search_prefilter, "candidates",
                        lambda node, index: seen.append(r := real(node, index)) or r)
    cache.page(snap, SCHEMA, query='name ~ "grid"', limit=50)
    assert seen and seen[0] is not None
