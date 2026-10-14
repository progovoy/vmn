"""Plan 23 S7: each group carries ``clause``, the query text selecting
exactly its rows in the same view (scope, top), quoted per the query
language; the no-value group's is ``= null``. ``failure_sig`` is a group
field."""
import random

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_group_fields import NONE

from vmn_exp.core import status as status_mod

SCHEMA = {"loss": {"goal": "min", "primary": True}}
ABSENT = object()
LRS = [0.01, 0.1, 1e-05, 3, -2, True, False, "adam", "two words", 'q"uote',
       "∅x", None, ABSENT]
TEAMS = ["x", 'say "hi"', "it's", ABSENT]
GROUPS = ["params.lr", "params.odd key/x", "tags.team", "branch", "status", "failure_sig",
          "parent", "code_verstr"]


class ParamFleet(Fleet):
    def _fold(self, i):
        row = super()._fold(i)
        rng = random.Random(self.specs[i]["verstr"])
        params = dict(row["params"], **{"odd key/x": rng.choice(["a", "b c"])})
        lr, team = rng.choice(LRS), rng.choice(TEAMS)
        if lr is not ABSENT:
            params["lr"] = lr
        return dict(row, params=params, tags={} if team is ABSENT else {"team": team})


@pytest.fixture(params=[1, 2, 3])
def fleet(monkeypatch, request):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    fleet = ParamFleet(request.param)
    jobs = fleet.seed_jobs(3, 60, T0, live=5)
    for _ in range(40):
        fleet.append(state=fleet.ended(T0))
    return fleet, jobs


def _views(jobs):
    return [{}, {"scope": jobs[0]}, {"top": True}, {"top": "jobs"}]


def _verstrs(rows):
    return [r["verstr"] for r in rows]


@pytest.mark.parametrize("group", GROUPS)
def test_a_groups_clause_selects_exactly_its_rows(fleet, group):
    fleet, jobs = fleet
    snap, cache = fleet.snapshot(), LeaderboardCache()
    for view in _views(jobs):
        out = cache.groups(snap, SCHEMA, group, limit=50, **view)
        for g in out["groups"]:
            if g["loose"]:
                assert g["clause"] is None
                continue
            rows = cache.groups(snap, SCHEMA, group, group_key=g["key"], limit=5000,
                                **view)["rows"]
            found = cache.page(snap, SCHEMA, query=g["clause"], limit=5000, **view)["rows"]
            assert sorted(_verstrs(found)) == sorted(_verstrs(rows)), (view, g["clause"])


def test_clauses_quote_keys_and_values_per_the_query_language(fleet):
    fleet, _ = fleet
    snap, cache = fleet.snapshot(), LeaderboardCache()
    clauses = {g["key"]: g["clause"] for g in
               cache.groups(snap, SCHEMA, "params.lr", limit=50)["groups"]}
    assert clauses["0.01"] == "params.lr = 0.01"
    assert clauses["true"] == "params.lr = true"
    assert clauses["two words"] == 'params.lr = "two words"'
    assert clauses['q"uote'] == "params.lr = 'q\"uote'"
    assert clauses[NONE] == "params.lr = null"
    odd = cache.groups(snap, SCHEMA, "params.odd key/x", limit=50)["groups"]
    assert {g["clause"] for g in odd} == {'params."odd key/x" = "a"', 'params."odd key/x" = "b c"'}
    branch = cache.groups(snap, SCHEMA, "branch", limit=50)["groups"][0]
    assert branch["clause"] == f'branch = "{branch["rows"][0]["branch"]}"'


def test_failed_runs_group_by_their_failure_signature(fleet):
    fleet, jobs = fleet
    snap, cache = fleet.snapshot(), LeaderboardCache()
    groups = cache.groups(snap, SCHEMA, "failure_sig", scope=jobs[1], limit=50)["groups"]
    signed = [g for g in groups if g["key"] != NONE]
    assert signed and all(r["failure_sig"] == g["key"] for g in signed for r in g["rows"])
    assert all(g["clause"].startswith("failure_sig = ") for g in signed)
