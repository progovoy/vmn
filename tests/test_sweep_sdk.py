"""``vmn_exp.sdk.sweep_params``: a trial's params, inside a sweep agent's child."""
import json

from vmn_exp.sdk import sweep_params


def test_sweep_params_reads_the_agents_env(monkeypatch):
    monkeypatch.setenv("VMN_SWEEP_PARAMS", json.dumps({"lr": 0.01, "act": "relu"}))
    assert sweep_params() == {"lr": 0.01, "act": "relu"}


def test_sweep_params_outside_a_sweep_is_empty(monkeypatch):
    monkeypatch.delenv("VMN_SWEEP_PARAMS", raising=False)
    assert sweep_params() == {}


def test_sweep_params_returns_a_copy_callers_may_mutate(monkeypatch):
    monkeypatch.setenv("VMN_SWEEP_PARAMS", json.dumps({"lr": 0.01}))
    sweep_params()["lr"] = 1
    assert sweep_params() == {"lr": 0.01}


def test_malformed_sweep_params_raise(monkeypatch):
    monkeypatch.setenv("VMN_SWEEP_PARAMS", "[1, 2]")
    try:
        sweep_params()
    except ValueError as exc:
        assert "VMN_SWEEP_PARAMS" in str(exc)
    else:
        raise AssertionError("expected ValueError")
