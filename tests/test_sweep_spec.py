"""Sweep specs: validation, grid enumeration, random draws, command templates."""
import math
import sys

import pytest

from vmn_exp.core.sweep.command import trial_command
from vmn_exp.core.sweep.spec import SpecError, grid_size, parse_spec, trial_limit
from vmn_exp.core.sweep.suggest import grid_point, random_point, suggest


def _spec(**overrides):
    data = {
        "method": "grid",
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {
            "lr": {"values": [0.1, 0.01]},
            "bs": {"values": [16, 32, 64]},
            "opt": {"value": "adam"},
        },
    }
    data.update(overrides)
    return parse_spec(data)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_goal_spellings_normalize_to_min_or_max():
    assert _spec()["metric"]["goal"] == "min"
    assert _spec(metric={"name": "acc", "goal": "maximize"})["metric"]["goal"] == "max"
    assert _spec(metric={"name": "acc", "goal": "max"})["metric"]["goal"] == "max"


@pytest.mark.parametrize(
    "overrides",
    [
        {"method": "hill-climb"},
        {"metric": {"goal": "min"}},
        {"metric": {"name": "loss", "goal": "sideways"}},
        {"parameters": {}},
        {"parameters": {"lr": 0.1}},
        {"parameters": {"lr": {"distribution": "uniform", "min": 1}}},
        {"parameters": {"lr": {"distribution": "log_uniform", "min": 0, "max": 1}}},
        {"parameters": {"lr": {"distribution": "beta", "min": 0, "max": 1}}},
        {"run_cap": 0},
        {"early_terminate": {"type": "hyperband", "min_iter": 3}},
    ],
)
def test_invalid_specs_are_rejected(overrides):
    with pytest.raises(SpecError):
        _spec(**overrides)


def test_grid_rejects_continuous_parameters():
    with pytest.raises(SpecError, match="grid"):
        _spec(parameters={"lr": {"distribution": "uniform", "min": 0.0, "max": 1.0}})


def test_yaml_style_scientific_strings_become_floats():
    # PyYAML reads `1e-4` (no dot) as a string.
    spec = _spec(
        method="random",
        parameters={"lr": {"distribution": "log_uniform", "min": "1e-4", "max": "1e-1"}},
    )
    assert spec["parameters"]["lr"]["min"] == pytest.approx(1e-4)


def test_min_max_integers_infer_int_uniform():
    spec = _spec(method="random", parameters={"layers": {"min": 1, "max": 4}})
    assert spec["parameters"]["layers"]["distribution"] == "int_uniform"


def test_median_early_terminate_defaults():
    spec = _spec(early_terminate={"type": "median"})
    assert spec["early_terminate"]["min_iter"] >= 1
    assert spec["early_terminate"]["check_interval_sec"] > 0


# ---------------------------------------------------------------------------
# grid
# ---------------------------------------------------------------------------


def test_grid_enumerates_the_cartesian_product_once():
    spec = _spec()
    assert grid_size(spec) == 6
    points = [grid_point(spec, n) for n in range(6)]
    assert len({tuple(sorted(p.items())) for p in points}) == 6
    assert all(p["opt"] == "adam" for p in points)
    assert {(p["lr"], p["bs"]) for p in points} == {
        (lr, bs) for lr in (0.1, 0.01) for bs in (16, 32, 64)
    }


def test_grid_order_is_by_parameter_name_not_spec_order():
    # The spec round-trips through yaml.dump(sort_keys=True) in metadata.
    a = _spec(parameters={"b": {"values": [1, 2]}, "a": {"values": [3, 4]}})
    b = _spec(parameters={"a": {"values": [3, 4]}, "b": {"values": [1, 2]}})
    assert [grid_point(a, n) for n in range(4)] == [grid_point(b, n) for n in range(4)]


def test_grid_expands_int_uniform():
    spec = _spec(parameters={"k": {"distribution": "int_uniform", "min": 1, "max": 3}})
    assert [grid_point(spec, n)["k"] for n in range(3)] == [1, 2, 3]


def test_grid_point_past_the_end_is_none():
    assert grid_point(_spec(), 6) is None


def test_trial_limit_is_grid_size_capped_by_run_cap():
    assert trial_limit(_spec()) == 6
    assert trial_limit(_spec(run_cap=4)) == 4
    assert trial_limit(_spec(run_cap=40)) == 6
    random_spec = _spec(method="random")
    assert trial_limit(random_spec) is None
    assert trial_limit(_spec(method="random", run_cap=5)) == 5


# ---------------------------------------------------------------------------
# random
# ---------------------------------------------------------------------------


def _random_spec(seed=0):
    return _spec(
        method="random",
        seed=seed,
        parameters={
            "lr": {"distribution": "log_uniform", "min": 1e-4, "max": 1e-1},
            "drop": {"distribution": "uniform", "min": 0.0, "max": 0.5},
            "layers": {"distribution": "int_uniform", "min": 1, "max": 4},
            "init": {"distribution": "normal", "mu": 0.0, "sigma": 1.0},
            "act": {"values": ["relu", "gelu"]},
            "opt": {"value": "adam"},
        },
    )


def test_random_draw_is_a_pure_function_of_seed_and_trial_index():
    spec = _random_spec()
    assert random_point(spec, 3) == random_point(spec, 3)
    assert random_point(spec, 3) != random_point(spec, 4)
    assert random_point(_random_spec(seed=1), 3) != random_point(spec, 3)


def test_random_draws_respect_the_distributions():
    spec = _random_spec()
    for n in range(50):
        p = random_point(spec, n)
        assert 1e-4 <= p["lr"] <= 1e-1
        assert 0.0 <= p["drop"] <= 0.5
        assert p["layers"] in (1, 2, 3, 4) and isinstance(p["layers"], int)
        assert math.isfinite(p["init"])
        assert p["act"] in ("relu", "gelu")
        assert p["opt"] == "adam"


def test_suggest_dispatches_on_method():
    assert suggest(_spec(), 2) == grid_point(_spec(), 2)
    spec = _random_spec()
    assert suggest(spec, 2) == random_point(spec, 2)


# ---------------------------------------------------------------------------
# command template
# ---------------------------------------------------------------------------


def test_list_template_substitutes_named_params():
    spec = _spec(command=["python", "train.py", "--lr", "${lr}", "--bs=${bs}"])
    assert trial_command(spec, {"lr": 0.01, "bs": 32, "opt": "adam"}) == [
        "python", "train.py", "--lr", "0.01", "--bs=32",
    ]


def test_wandb_style_tokens_expand():
    spec = _spec(program="train.py", command=["${env}", "${interpreter}", "${program}", "${args}"])
    cmd = trial_command(spec, {"lr": 0.01, "bs": 32, "opt": "adam"})
    assert cmd == [sys.executable, "train.py", "--bs=32", "--lr=0.01", "--opt=adam"]


def test_args_no_hyphens_and_json():
    spec = _spec(command=["run", "${args_no_hyphens}", "${args_json}"])
    cmd = trial_command(spec, {"lr": 0.01, "bs": 32, "opt": "adam"})
    assert cmd[:4] == ["run", "bs=32", "lr=0.01", "opt=adam"]
    assert cmd[4] == '{"bs": 32, "lr": 0.01, "opt": "adam"}'


def test_program_alone_implies_the_wandb_default_command():
    spec = _spec(program="train.py")
    assert trial_command(spec, {"lr": 0.1, "bs": 16, "opt": "adam"}) == [
        sys.executable, "train.py", "--bs=16", "--lr=0.1", "--opt=adam",
    ]


def test_agent_command_overrides_the_spec_with_the_same_substitution():
    spec = _spec(command=["python", "a.py"])
    assert trial_command(spec, {"lr": 0.1}, override=["b.sh", "${lr}"]) == ["b.sh", "0.1"]


def test_unknown_placeholder_and_missing_command_are_errors():
    with pytest.raises(SpecError, match="nope"):
        trial_command(_spec(command=["x", "${nope}"]), {"lr": 0.1})
    with pytest.raises(SpecError, match="command"):
        trial_command(_spec(), {"lr": 0.1})
