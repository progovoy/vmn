"""An incomplete sweep in ``vmn-exp ui`` (plan 20 A7/D12): the leaderboard's
cached and incrementally derived rows answer as the uncached pipeline, and the
run detail carries ``sweep_planned``/``sweep_trials`` with the fleet expecting
the planned trials."""
import copy
import datetime

import pytest
from run_code_seed import client, finished_state, run_url, seed_run
from vmn_exp.core import status as status_mod
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.log import experiment_row
from vmn_exp.core.sweep.spec import parse_spec
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui.readers import experiments as exp_reader

APP = "app"
NOW = datetime.datetime(2026, 3, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
SWEEP = "1.0.0-dev.r0000"
SPEC = parse_spec({
    "method": "grid",
    "metric": {"name": "loss", "goal": "min"},
    "parameters": {"x": {"values": [1, 2, 3, 4]}},
})


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _finished():
    return {"state": "finished", "exit_code": 0, "started_at": _iso(NOW),
            "finished_at": _iso(NOW), "heartbeat": _iso(NOW)}


def _running():
    return {"state": "running", "exit_code": None, "started_at": _iso(NOW),
            "heartbeat": _iso(NOW), "heartbeat_interval_sec": 10}


def _trial_log(n):
    tags = {"sweep": SWEEP, "sweep_trial": str(n), "sweep_attempt": "0"}
    return [{"timestamp": "t", "type": "create", "tags": tags}]


def _snapshot(trials, generation=1, live=()):
    rows = [experiment_row(1, {"verstr": SWEEP, "timestamp": "2026-01-01T00:00:00Z",
                               "sweep": SPEC}, [])]
    states = {SWEEP: None}
    for n in range(trials):
        verstr = f"1.0.0-dev.r{n + 1:04d}"
        meta = {"verstr": verstr, "parent": SWEEP, "timestamp": f"2026-01-01T00:00:0{n + 1}Z"}
        rows.append(experiment_row(n + 2, meta, _trial_log(n)))
        states[verstr] = _running() if n in live else _finished()
    return IndexSnapshot.build(APP, generation, rows, states)


def _reference(snap):
    rows = copy.deepcopy(list(snap.rows))
    return exp_reader.leaderboard(rows, dict(snap.run_states), {}, limit=50)


def _outer(result):
    return next(r for r in result["rows"] if r["verstr"] == SWEEP)


def _strip(result):
    return [{k: v for k, v in r.items() if k not in ("stale_sec", "duration_sec")}
            for r in result["rows"]]


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or NOW)


def test_the_uncached_pipeline_says_created_until_every_trial_ran():
    assert _outer(_reference(_snapshot(3)))["tree_status"] == "created"
    assert _outer(_reference(_snapshot(4)))["tree_status"] == "succeeded"


def test_a_new_generation_derives_the_same_rollup():
    cache = lb.LeaderboardCache()
    first = cache.page(_snapshot(3), {}, limit=50)
    assert (_outer(first)["tree_status"], _outer(first)["sweep_trials"]) == ("created", 3)
    snap = _snapshot(4, generation=2)
    second = cache.page(snap, {}, limit=50)
    assert (_outer(second)["tree_status"], _outer(second)["sweep_trials"]) == ("succeeded", 4)
    assert _strip(second) == _strip(_reference(snap))


def test_a_trial_finishing_in_a_new_generation_leaves_it_created():
    cache = lb.LeaderboardCache()
    assert _outer(cache.page(_snapshot(3, live={2}), {}, limit=50))["tree_status"] == "running"
    snap = _snapshot(3, generation=2)
    got = cache.page(snap, {}, limit=50)
    assert _outer(got)["tree_status"] == "created"
    assert _strip(got) == _strip(_reference(snap))


def test_live_rows_patched_over_time_match_the_reference(monkeypatch):
    cache = lb.LeaderboardCache(bucket_sec=2)
    snap = _snapshot(3, live={1})
    assert _outer(cache.page(snap, {}, limit=50))["tree_status"] == "running"
    later = NOW + datetime.timedelta(hours=1)
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or later)
    got = cache.page(snap, {}, limit=50)
    assert _outer(got)["tree_status"] == "stuck"
    assert _strip(got) == _strip(_reference(snap))


OUTER = "0.0.1-dev.r1"


def _seed_sweep(app_layout, trials):
    seed_run(app_layout, OUTER, 1, sweep=SPEC, name="sw")
    for n in range(trials):
        tags = {"sweep": OUTER, "sweep_trial": str(n), "sweep_attempt": "0"}
        seed_run(app_layout, f"0.0.1-dev.r{n + 2}", n + 2, finished_state(0), parent=OUTER,
                 entries=[{"type": "create", "tags": tags}])


def _status(app_layout):
    pytest.importorskip("fastapi")
    resp = client(app_layout).get(run_url(app_layout, OUTER))
    assert resp.status_code == 200, resp.text
    return resp.json()["status"]


def test_the_run_detail_reports_the_incomplete_sweep(app_layout):
    _seed_sweep(app_layout, 3)
    status = _status(app_layout)
    assert status["tree_status"] == "created"
    assert (status["sweep_planned"], status["sweep_trials"]) == (4, 3)
    assert status["fleet"]["expected"] == 4
    assert status["fleet"]["counts"]["waiting"] == 1


def test_the_run_detail_of_a_complete_sweep_succeeded(app_layout):
    _seed_sweep(app_layout, 4)
    status = _status(app_layout)
    assert status["tree_status"] == "succeeded"
    assert (status["sweep_planned"], status["sweep_trials"]) == (4, 4)
