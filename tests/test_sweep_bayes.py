"""Bayes sweeps delegate suggestions to Optuna's TPE sampler."""
import builtins

import pytest

from vmn_exp.core.sweep.spec import SpecError, parse_spec
from vmn_exp.core.sweep.suggest import suggest


def _spec(**params):
    return parse_spec({
        "method": "bayes",
        "metric": {"name": "loss", "goal": "min"},
        "parameters": params or {
            "lr": {"distribution": "log_uniform", "min": 1e-4, "max": 1e-1},
            "layers": {"distribution": "int_uniform", "min": 1, "max": 4},
            "act": {"values": ["relu", "gelu"]},
            "opt": {"value": "adam"},
        },
    })


def test_bayes_suggestions_come_from_the_history():
    pytest.importorskip("optuna")
    spec = _spec()
    history = [
        ({"lr": 1e-3, "layers": 2, "act": "relu", "opt": "adam"}, 0.5),
        ({"lr": 1e-2, "layers": 3, "act": "gelu", "opt": "adam"}, 0.3),
    ]
    params = suggest(spec, 2, history=history)
    assert 1e-4 <= params["lr"] <= 1e-1
    assert params["layers"] in (1, 2, 3, 4)
    assert params["act"] in ("relu", "gelu")
    assert params["opt"] == "adam"
    # Seeded by the trial index: the same history yields the same suggestion.
    assert suggest(spec, 2, history=history) == params


def test_bayes_tolerates_history_outside_the_space():
    pytest.importorskip("optuna")
    history = [({"lr": 5.0, "layers": 2, "act": "relu", "opt": "adam"}, 0.5)]
    assert "lr" in suggest(_spec(), 1, history=history)


def test_bayes_rejects_a_normal_distribution():
    pytest.importorskip("optuna")
    spec = _spec(w={"distribution": "normal", "mu": 0.0, "sigma": 1.0})
    with pytest.raises(SpecError, match="normal"):
        suggest(spec, 0, history=[])


def test_bayes_without_optuna_is_a_clear_error(monkeypatch):
    real_import = builtins.__import__

    def no_optuna(name, *args, **kwargs):
        if name == "optuna" or name.startswith("optuna."):
            raise ImportError("No module named 'optuna'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_optuna)
    with pytest.raises(SpecError, match="pip install optuna"):
        suggest(_spec(), 0, history=[])
