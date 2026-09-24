"""Live rows are patched into a cached order of the terminal rows: a new time
bucket re-derives, re-filters and re-places only the live rows (and the
tree_status of their ancestors), never re-sorting every row. The answer must
equal the uncached pipeline's exactly."""
import copy
import datetime
import random

import pytest

from version_stamp.core import experiment_status as status_mod
from version_stamp.core.experiment_index_snapshot import IndexSnapshot
from version_stamp.core.experiment_log import experiment_row
from version_stamp.ui import leaderboard_cache as lb
from version_stamp.ui.readers import experiments as exp_reader

APP = "app"
T0 = datetime.datetime(2026, 3, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
VOLATILE = ("stale_sec", "duration_sec")


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(rng):
    kind = rng.choice(["ok", "fail", "none", "running", "running", "old"])
    if kind == "none":
        return None
    if kind in ("ok", "fail"):
        return {"state": "finished", "exit_code": 0 if kind == "ok" else 2,
                "started_at": _iso(T0), "heartbeat": _iso(T0)}
    # Live: the heartbeat's age decides when it turns stuck as time moves.
    age = rng.choice([0, 20, 50, 80, 200]) if kind == "running" else 5000
    return {"state": "running", "exit_code": None, "started_at": _iso(T0),
            "heartbeat": _iso(T0 - datetime.timedelta(seconds=age)),
            "heartbeat_interval_sec": 10}


def _metric(rng):
    return rng.choice([None, "missing", 0.5, 1, 2.5, 2.5, float("nan"), -3, "str"])


def _random_snapshot(rng, n, generation=1):
    rows, states = [], {}
    for i in range(n):
        verstr = f"1.0.0-dev.r{i:04d}"
        meta = {"verstr": verstr}
        if rng.random() < 0.9:
            meta["timestamp"] = f"2026-01-01T00:00:{rng.randrange(8):02d}Z"
        if i and rng.random() < 0.4:
            meta["parent"] = f"1.0.0-dev.r{rng.randrange(n):04d}"
        values = {}
        for name in ("loss", "acc"):
            value = _metric(rng)
            if value != "missing":
                values[name] = value
        state = _state(rng)
        if state and state["exit_code"] is None and rng.random() < 0.5:
            values["live_only"] = rng.random()
        log = [{"timestamp": "t", "type": "create",
                "params": {"opt": rng.choice(["adam", "sgd"])}},
               {"timestamp": "t", "type": "metrics", "values": values}]
        rows.append(experiment_row(i + 1, meta, log))
        states[verstr] = state
    return IndexSnapshot.build(APP, generation, rows, states)


QUERIES = [None, 'status = "running"', 'tree_status = "stuck"',
           "metrics.loss < 2", 'params.opt = "adam" or status != "failed"',
           'kind = "outer" and not tree_status = "succeeded"']
STATUSES = [None, "running", "stuck,failed", "succeeded,created"]
SORTS = [None, "loss", "acc", "timestamp", "live_only", "nope"]
SCHEMAS = [{}, {"loss": {"goal": "min", "primary": True}}, {"acc": {"goal": "max"}}]


def _at(monkeypatch, when):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


def _reference(snap, schema, **params):
    rows = copy.deepcopy(list(snap.rows))
    return exp_reader.leaderboard(rows, dict(snap.run_states), schema, **params)


def _strip(result):
    return [{k: v for k, v in r.items() if k not in VOLATILE} for r in result["rows"]]


def _same(got, want):
    assert got["total"] == want["total"]
    assert _strip(got) == _strip(want)


@pytest.mark.parametrize("seed", range(12))
def test_patched_pages_equal_the_uncached_pipeline(monkeypatch, seed):
    rng = random.Random(seed)
    snap = _random_snapshot(rng, rng.randrange(1, 60))
    cache = lb.LeaderboardCache(bucket_sec=2)
    for step in range(4):
        _at(monkeypatch, T0 + datetime.timedelta(seconds=37 * step))
        for _ in range(10):
            params = dict(
                sort=rng.choice(SORTS), order=rng.choice([None, "asc", "desc"]),
                status=rng.choice(STATUSES), query=rng.choice(QUERIES),
                offset=rng.randrange(0, 20), limit=rng.choice([1, 5, 30, 100]),
                last=rng.choice([None, None, None, 7]),
            )
            schema = rng.choice(SCHEMAS)
            _same(cache.page(snap, schema, **params), _reference(snap, schema, **params))


def _counted(monkeypatch, module, name, calls):
    real = getattr(module, name)

    def counted(*args, **kwargs):
        calls[name] = calls.get(name, 0) + 1
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, counted)


def _big_snapshot(n, live):
    rng = random.Random(7)
    rows, states = [], {}
    for i in range(n):
        verstr = f"1.0.0-dev.r{i:05d}"
        meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i % 60:02d}Z"}
        if i in live:
            meta["parent"] = "1.0.0-dev.r00000"
        log = [{"timestamp": "t", "type": "metrics", "values": {"loss": rng.random()}}]
        rows.append(experiment_row(i + 1, meta, log))
        states[verstr] = (
            {"state": "running", "exit_code": None, "heartbeat": _iso(T0),
             "heartbeat_interval_sec": 10}
            if i in live else {"state": "finished", "exit_code": 0}
        )
    return IndexSnapshot.build(APP, 1, rows, states)


def test_successive_buckets_do_not_sort_or_annotate_every_row(monkeypatch):
    live = {11, 5000, 19999}
    snap = _big_snapshot(20000, live)
    cache = lb.LeaderboardCache(bucket_sec=2)
    _at(monkeypatch, T0)
    params = dict(sort="loss", order="asc", offset=0, limit=50)
    cache.page(snap, {}, **params)
    cache.page(snap, {}, sort="timestamp", limit=50)
    cache.page(snap, {}, status="stuck", limit=50)

    calls = {}
    _counted(monkeypatch, lb, "sort_rows", calls)
    _counted(monkeypatch, lb, "annotate_rows", calls)
    _counted(monkeypatch, exp_reader, "sort_by_metric", calls)
    for step in range(1, 6):
        # Past 60s the heartbeat is stale: the live rows move from running to stuck.
        _at(monkeypatch, T0 + datetime.timedelta(seconds=20 * step))
        got = cache.page(snap, {}, status="stuck", limit=50)
        assert got["total"] == (3 if step >= 4 else 0)
        cache.page(snap, {}, **params)
        cache.page(snap, {}, sort="timestamp", limit=50, offset=19950)
    assert calls == {}

    root = cache.page(snap, {}, query='verstr = "1.0.0-dev.r00000"', limit=1)["rows"][0]
    assert root["tree_status"] == "stuck"
    _same(cache.page(snap, {}, **params), _reference(snap, {}, **params))


def test_archived_rows_are_hidden_unless_asked_for(monkeypatch):
    rng = random.Random(3)
    snap = _random_snapshot(rng, 30)
    archived = {r["verstr"] for r in snap.rows[::3]}
    rows = [dict(r, archived=True) if r["verstr"] in archived else r for r in snap.rows]
    snap = IndexSnapshot.build(APP, 1, rows, snap.run_states)
    _at(monkeypatch, T0)
    cache = lb.LeaderboardCache()

    shown = cache.page(snap, {}, sort="loss", limit=100)
    assert shown["total"] == 20
    assert not {r["verstr"] for r in shown["rows"]} & archived
    everything = cache.page(snap, {}, sort="loss", limit=100, archived=True)
    _same(everything, _reference(snap, {}, sort="loss", limit=100))
    assert cache.etag(snap, {}, limit=10) != cache.etag(snap, {}, limit=10, archived=True)
    assert cache.facets(snap)["total"] == 20
    assert cache.facets(snap, archived=True)["total"] == 30
