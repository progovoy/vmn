"""Leaderboard memoization: the status/tree/filter/sort pipeline runs once per
index generation (and per time bucket while runs are live), pages are slices."""
import copy
import datetime

import pytest

from version_stamp.core import experiment_status as status_mod
from version_stamp.core.experiment_index_snapshot import IndexSnapshot
from version_stamp.core.experiment_log import experiment_row
from version_stamp.core.experiment_query import QueryError
from version_stamp.ui import leaderboard_cache as lb
from version_stamp.ui.readers import experiments as exp_reader

APP = "app"
NOW = datetime.datetime.now(datetime.timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _finished(code=0):
    return {"state": "finished", "exit_code": code, "started_at": _iso(NOW),
            "finished_at": _iso(NOW), "heartbeat": _iso(NOW)}


def _running():
    return {"state": "running", "exit_code": None, "started_at": _iso(NOW),
            "heartbeat": _iso(NOW), "heartbeat_interval_sec": 30}


def _snapshot(n=20, generation=1, live=(), parent_of=None):
    parent_of = parent_of or {}
    rows, states = [], {}
    for i in range(n):
        verstr = f"1.0.0-dev.r{i:04d}"
        meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i % 60:02d}.{i:06d}Z",
                "branch": f"b{i % 3}"}
        if i in parent_of:
            meta["parent"] = f"1.0.0-dev.r{parent_of[i]:04d}"
        log = [{"timestamp": "t", "type": "create", "params": {"lr": i / 100, "opt": "adam"}},
               {"timestamp": "t", "type": "metrics", "values": {"loss": (i * 7) % 11 / 10}}]
        rows.append(experiment_row(i + 1, meta, log))
        states[verstr] = _running() if i in live else _finished(1 if i % 4 == 0 else 0)
    return IndexSnapshot.build(APP, generation, rows, states)


def _counting(monkeypatch, name):
    calls = []
    real = getattr(lb, name)

    def counted(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(lb, name, counted)
    return calls


def _reference(snap, schema, **params):
    rows = copy.deepcopy(list(snap.rows))
    return exp_reader.leaderboard(rows, dict(snap.run_states), schema, **params)


def _strip_time(result):
    rows = result["rows"] if isinstance(result, dict) else result
    return [{k: v for k, v in r.items() if k not in ("stale_sec", "duration_sec")} for r in rows]


PARAMS = [
    dict(limit=5),
    dict(sort="loss", order="asc", limit=7, offset=3),
    dict(sort="timestamp", limit=10),
    dict(status="failed", limit=50),
    dict(query="metrics.loss < 0.5 and params.opt = \"adam\"", limit=50),
    dict(last=6, sort="loss", limit=50),
]


@pytest.mark.parametrize("params", PARAMS)
def test_pages_match_the_uncached_pipeline(params):
    snap = _snapshot(live={2, 5}, parent_of={3: 1, 4: 1})
    schema = {"loss": {"goal": "min"}}
    got = lb.LeaderboardCache().page(snap, schema, **params)
    want = _reference(snap, schema, **params)
    assert got["total"] == want["total"]
    assert _strip_time(got) == _strip_time(want)


def test_the_pipeline_runs_once_per_generation(monkeypatch):
    tree_calls = _counting(monkeypatch, "annotate_tree")
    sort_calls = _counting(monkeypatch, "sort_rows")
    cache = lb.LeaderboardCache()
    snap = _snapshot(n=100)

    for offset in range(0, 100, 10):
        cache.page(snap, {}, sort="loss", offset=offset, limit=10)
    assert len(tree_calls) == 1
    assert len(sort_calls) == 1

    cache.page(snap, {}, sort="timestamp", limit=10)
    assert len(tree_calls) == 1  # a new ordering re-sorts, never re-annotates
    assert len(sort_calls) == 2

    cache.page(_snapshot(n=100, generation=2), {}, sort="loss", limit=10)
    assert len(tree_calls) == 2


def test_only_live_rows_are_rederived_as_time_passes(monkeypatch):
    status_calls = _counting(monkeypatch, "status_fields")
    cache = lb.LeaderboardCache(bucket_sec=2)
    snap = _snapshot(n=50, live={7})

    cache.page(snap, {}, limit=10)
    assert len(status_calls) == 50

    later = NOW + datetime.timedelta(seconds=10)
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or later)
    cache.page(snap, {}, limit=10)
    assert len(status_calls) == 51  # the running row only


def test_a_stale_heartbeat_turns_stuck_within_a_bucket(monkeypatch):
    cache = lb.LeaderboardCache(bucket_sec=2)
    snap = _snapshot(n=5, live={2}, parent_of={2: 1})
    by_verstr = {r["verstr"]: r for r in cache.page(snap, {}, limit=10)["rows"]}
    assert by_verstr["1.0.0-dev.r0002"]["status"] == "running"

    later = NOW + datetime.timedelta(hours=1)
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or later)
    by_verstr = {r["verstr"]: r for r in cache.page(snap, {}, limit=10)["rows"]}
    assert by_verstr["1.0.0-dev.r0002"]["status"] == "stuck"
    assert by_verstr["1.0.0-dev.r0001"]["tree_status"] == "stuck"
    assert cache.page(snap, {}, status="stuck", limit=10)["total"] == 1


def test_etag_tracks_generation_params_and_live_time(monkeypatch):
    cache = lb.LeaderboardCache(bucket_sec=2)
    done = _snapshot(n=10)
    tag = cache.etag(done, {}, sort="loss", limit=10)
    assert tag == cache.etag(done, {}, sort="loss", limit=10)
    assert tag != cache.etag(done, {}, sort="loss", limit=10, offset=10)
    assert tag != cache.etag(done, {"loss": {"goal": "max"}}, sort="loss", limit=10)
    assert tag != cache.etag(_snapshot(n=10, generation=2), {}, sort="loss", limit=10)

    live = _snapshot(n=10, generation=3, live={1})
    live_tag = cache.etag(live, {}, limit=10)
    later = NOW + datetime.timedelta(seconds=30)
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or later)
    assert cache.etag(done, {}, sort="loss", limit=10) == tag  # nothing live: timeless
    assert cache.etag(live, {}, limit=10) != live_tag


def test_a_bad_query_raises():
    with pytest.raises(QueryError):
        lb.LeaderboardCache().page(_snapshot(), {}, query="statuz = 1", limit=5)


def test_without_limit_a_plain_list_capped_at_max_page():
    rows = lb.LeaderboardCache(max_page=7).page(_snapshot(n=20), {})
    assert isinstance(rows, list) and len(rows) == 7


def test_facets_are_computed_once_per_generation():
    cache = lb.LeaderboardCache()
    snap = _snapshot(n=9)
    facets = cache.facets(snap)
    assert facets == {
        "branches": ["b0", "b1", "b2"],
        "metric_keys": ["loss", "lr"],
        "param_keys": ["lr", "opt"],
        "total": 9,
    }
    assert cache.facets(snap) is facets
