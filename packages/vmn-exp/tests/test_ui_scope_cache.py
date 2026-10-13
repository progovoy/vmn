"""Plan 23 S2: ``scope=<verstr>`` (the run's subtree without the run) and
``top`` (top-level runs only) filter every leaderboard answer — pages,
columns, importance, facets and groups — and must answer what filtering the
uncached pipeline's rows answers, across index generations derived by deltas
(re-parenting included) and time buckets."""
import datetime
import random

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.core import status as status_mod
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_facets import visible
from vmn_exp.ui.readers.experiments import apply_filters, facets, sort_rows

VOLATILE = ("stale_sec", "duration_sec", "job")  # job: test_ui_jobs_view.py
SCHEMAS = [{}, {"loss": {"goal": "min", "primary": True}}]
SORTS = [None, "loss", "acc", "timestamp"]
STATUSES = [None, "running", "succeeded,created"]
QUERIES = [None, "metrics.loss < 0.6", 'kind = "inner"', "depth >= 2"]


def _at(monkeypatch, when):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


def _strip(rows):
    return [{k: v for k, v in r.items() if k not in VOLATILE} for r in rows]


def _wanted(snap, fleet, schema, scope=None, top=False, sort=None, order=None, status=None,
            query=None, archived=False):
    """The uncached pipeline over the in-scope rows."""
    rows = LeaderboardCache().rows(snap, archived=True)
    if scope is not None:
        rows = [r for r in rows if scope in fleet.ancestors(r["verstr"])]
    if top:
        rows = [r for r in rows if r["depth"] == 0]
    rows = apply_filters(visible(rows, archived), status, query, snap)
    return sort_rows(rows, schema, sort=sort, order=order)


def _cases(rng, scopes):
    cases = []
    for _ in range(14):
        cases.append(dict(
            scope=rng.choice(scopes), sort=rng.choice(SORTS), order=rng.choice([None, "asc"]),
            status=rng.choice(STATUSES), query=rng.choice(QUERIES),
            archived=rng.random() < 0.3))
    cases.append(dict(top=True, sort="loss"))
    cases.append(dict(top=True, status="running", query="metrics.loss < 0.6"))
    return [(rng.choice(SCHEMAS), case) for case in cases]


def _check(cache, snap, fleet, cases):
    for schema, case in cases:
        if case.get("scope") not in (None, *fleet.states):
            continue
        want = _wanted(snap, fleet, schema, **case)
        got = cache.page(snap, schema, limit=10**6, **case)
        assert got["total"] == len(want), case
        assert _strip(got["rows"]) == _strip(want), case
        if case.get("scope"):
            under = dict(case, scope=None, query=" and ".join(
                [f'under("{case["scope"]}")'] + ([case["query"]] if case["query"] else [])))
            assert cache.page(snap, schema, limit=10**6, **under)["total"] == len(want)


@pytest.mark.parametrize("seed", range(5))
def test_scoped_pages_equal_the_filtered_pipeline(monkeypatch, seed):
    rng = random.Random(seed)
    now = T0
    _at(monkeypatch, now)
    fleet = Fleet(seed)
    roots = fleet.seed(rng.randrange(150, 300), now, sweeps=4, live=12)
    nested = fleet.append(parent=roots[0])
    for _ in range(6):
        fleet.append(parent=nested)
    cases = _cases(rng, roots + [nested])
    cache = LeaderboardCache(bucket_sec=2, size=256)
    _check(cache, fleet.snapshot(), fleet, cases)
    for _ in range(6):
        now += datetime.timedelta(seconds=rng.choice([1, 7, 61]))
        _at(monkeypatch, now)
        fleet.mutate(now, rng.randrange(1, 6))
        snap = fleet.snapshot()
        _check(cache, snap, fleet, cases)
        _at(monkeypatch, now + datetime.timedelta(seconds=90))
        _check(cache, snap, fleet, cases)


def test_relinking_a_nested_job_moves_its_subtree_between_scopes(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(4)
    root = fleet.append()
    one, two = fleet.append(parent=root), fleet.append(parent=root)
    job = fleet.append(parent=one)
    kids = [fleet.append(parent=job) for _ in range(4)]
    for _ in range(100):
        fleet.append()
    cache = LeaderboardCache()
    verstrs = lambda snap, scope: {r["verstr"] for r in cache.page(  # noqa: E731
        snap, {}, limit=1000, scope=scope)["rows"]}
    snap = fleet.snapshot()
    assert verstrs(snap, one) == {job, *kids} and verstrs(snap, two) == set()
    fleet.edit(fleet.index(job), parent=two)
    snap = fleet.snapshot()
    assert verstrs(snap, one) == set() and verstrs(snap, two) == {job, *kids}
    assert verstrs(snap, root) == {one, two, job, *kids}


def test_columns_importance_facets_and_groups_follow_the_scope(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(7)
    roots = fleet.seed(300, T0, sweeps=3, live=5)
    snap, schema = fleet.snapshot(), {"loss": {"goal": "min"}}
    cache, scope = LeaderboardCache(), roots[1]
    rows = _wanted(snap, fleet, schema, scope=scope, sort="loss")
    cols = cache.columns(snap, schema, ["metrics.loss"], limit=20, sort="loss", scope=scope)
    assert cols["verstrs"] == [r["verstr"] for r in rows[:20]]
    assert cols["total"] == len(rows)
    by_query = cache.importance(snap, schema, "loss", query=f'under("{scope}")')
    assert cache.importance(snap, schema, "loss", scope=scope) == by_query
    filtered = _wanted(snap, fleet, schema, scope=scope, status="succeeded")
    assert cache.facets(snap, scope=scope, status="succeeded") == facets(filtered)
    assert cache.facets(snap, query="metrics.loss < 0.5")["total"] == len(
        _wanted(snap, fleet, schema, query="metrics.loss < 0.5"))
    groups = cache.groups(snap, schema, "branch", scope=scope, rows_per_group=100)
    assert groups["total_rows"] == len(rows)
    assert {r["verstr"] for g in groups["groups"] for r in g["rows"]} == {
        r["verstr"] for r in rows}


def test_an_unknown_scope_is_a_lookup_error(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(8)
    fleet.seed(50, T0)
    snap, cache = fleet.snapshot(), LeaderboardCache()
    with pytest.raises(LookupError):
        cache.page(snap, {}, limit=5, scope="1.0.0-dev.nope")


@pytest.mark.parametrize("seed", range(3))
def test_a_scope_and_an_indexed_text_clause_answer_together(monkeypatch, seed):
    # The search index narrows the slots a ~ clause can match (plan 23 S8)
    # and the scope narrows them to a subtree (S2): both at once must still
    # answer what the uncached pipeline does.
    rng = random.Random(seed)
    _at(monkeypatch, T0)
    fleet = Fleet(seed)
    roots = fleet.seed(300, T0, sweeps=4, live=8)
    cases = [(SCHEMAS[1], dict(scope=scope, query=query, sort="loss"))
             for scope in roots[:4] for query in ('verstr ~ "1"', '(verstr ~ "7" or verstr ~ "3")')]
    cache = LeaderboardCache(bucket_sec=2, size=256)
    _check(cache, fleet.snapshot(), fleet, cases)
    for _ in range(3):
        fleet.mutate(T0, rng.randrange(1, 6))
        _check(cache, fleet.snapshot(), fleet, cases)
