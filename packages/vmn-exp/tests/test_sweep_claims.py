"""Server-less trial claims: ``create_exclusive`` slots under ``vmn-sweeps``."""
import threading

import pytest

from vmn_exp.core.reserved import is_reserved_app
from vmn_exp.core.sweep.claims import (
    SWEEP_APP,
    attach_run,
    claim_next_trial,
    claim_retry,
    claimed_trials,
    list_claims,
)
from vmn_exp.core.sweep.spec import parse_spec
from vmn_exp.core.sweep.suggest import grid_point
from vmn_exp.snapshot import open_storage

APP = "my_app"
SWEEP = "0.0.1-dev.aaaaaaa.bbbbbbb"


def _local(tmp_path):
    return open_storage(vmn_root_path=str(tmp_path), subdir="experiments")


def _grid(run_cap=None, n_values=6):
    data = {
        "method": "grid",
        "metric": {"name": "loss", "goal": "min"},
        "parameters": {"x": {"values": list(range(n_values))}},
    }
    if run_cap:
        data["run_cap"] = run_cap
    return parse_spec(data)


def _drain(storage, spec, agent, out, sweep=SWEEP):
    while True:
        claim = claim_next_trial(storage, APP, sweep, spec, agent=agent)
        if claim is None:
            return
        out.append(claim)


def test_the_sweep_pseudo_app_is_reserved():
    assert is_reserved_app(SWEEP_APP)


def test_sequential_claims_walk_the_grid_then_stop(tmp_path):
    storage, spec = _local(tmp_path), _grid()
    claims = []
    _drain(storage, spec, "a", claims)
    assert [c["trial"] for c in claims] == list(range(6))
    assert [c["params"] for c in claims] == [grid_point(spec, n) for n in range(6)]
    assert claim_next_trial(storage, APP, SWEEP, spec) is None


def test_run_cap_bounds_the_claims(tmp_path):
    storage, spec = _local(tmp_path), _grid(run_cap=3)
    claims = []
    _drain(storage, spec, "a", claims)
    assert [c["trial"] for c in claims] == [0, 1, 2]


def test_sweeps_do_not_share_slots(tmp_path):
    storage, spec = _local(tmp_path), _grid(run_cap=2)
    a, b = [], []
    _drain(storage, spec, "a", a, sweep=SWEEP)
    _drain(storage, spec, "a", b, sweep=SWEEP + ".r2")
    assert [c["trial"] for c in a] == [c["trial"] for c in b] == [0, 1]


def test_claimed_trials_come_from_the_listing_alone(tmp_path, monkeypatch):
    storage, spec = _local(tmp_path), _grid(run_cap=3)
    _drain(storage, spec, "a", [])
    claim_retry(storage, APP, SWEEP, 1, agent="a")

    def no_loads(*_args, **_kwargs):
        raise AssertionError("claimed_trials must not load a claim")

    monkeypatch.setattr(storage, "load_metadata", no_loads)
    monkeypatch.setattr(storage, "load", no_loads)
    assert claimed_trials(storage, APP, SWEEP) == {0, 1, 2}


def test_claims_are_listed_with_their_run(tmp_path):
    storage, spec = _local(tmp_path), _grid(run_cap=2)
    first = claim_next_trial(storage, APP, SWEEP, spec, agent="host1")
    attach_run(storage, first, "run-verstr")
    listed = list_claims(storage, APP, SWEEP)
    assert [(c["trial"], c.get("run"), c["agent"]) for c in listed] == [
        (0, "run-verstr", "host1")
    ]


def _race(storage_factory, spec, n_agents=4):
    results, errors = [[] for _ in range(n_agents)], []
    barrier = threading.Barrier(n_agents)

    def agent(i):
        try:
            storage = storage_factory()
            barrier.wait()
            _drain(storage, spec, f"agent{i}", results[i])
        except Exception as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=agent, args=(i,)) for i in range(n_agents)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    return [c["trial"] for r in results for c in r]


def test_parallel_agents_on_a_shared_dir_never_duplicate_a_trial(tmp_path):
    spec = _grid(n_values=40)
    trials = _race(lambda: _local(tmp_path), spec)
    assert sorted(trials) == list(range(40))


def test_parallel_agents_on_a_shared_bucket_never_duplicate_a_trial(monkeypatch):
    pytest.importorskip("moto")
    from s3_helpers import mocked_bucket, s3_storage

    spec = _grid(n_values=12)
    with mocked_bucket(monkeypatch):
        trials = _race(s3_storage, spec, n_agents=3)
        assert sorted(trials) == list(range(12))
        assert [c["trial"] for c in list_claims(s3_storage(), APP, SWEEP)] == list(range(12))


def test_a_retry_is_claimed_once_and_keeps_the_trial_params(tmp_path):
    storage, spec = _local(tmp_path), _grid(run_cap=2)
    original = claim_next_trial(storage, APP, SWEEP, spec)
    retry = claim_retry(storage, APP, SWEEP, original["trial"], agent="b")
    assert retry["trial"] == original["trial"]
    assert retry["attempt"] == 1
    assert retry["params"] == original["params"]
    # A second retrier takes the next attempt, never the same one.
    again = claim_retry(storage, APP, SWEEP, original["trial"], agent="c")
    assert again["attempt"] == 2
    # Retries never consume a new trial slot.
    assert claim_next_trial(storage, APP, SWEEP, spec)["trial"] == 1
