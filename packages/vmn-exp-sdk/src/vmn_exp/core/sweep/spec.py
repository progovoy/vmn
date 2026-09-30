"""The sweep spec: validation and normalization (see docs/vmn-exp/sweeps.md).

The normalized spec is what the sweep's metadata stores and what every agent
reads, so it only holds plain YAML values. Parameters are always walked in
sorted name order: the metadata round-trips through ``yaml.dump(sort_keys=True)``,
which forgets the spec's own order.
"""
import math

import yaml

METHODS = ("grid", "random", "bayes")
DISTRIBUTIONS = ("uniform", "log_uniform", "int_uniform", "normal", "categorical")
_GOALS = {"min": "min", "minimize": "min", "max": "max", "maximize": "max"}
_EARLY_TERMINATE_DEFAULTS = {"min_iter": 3, "min_trials": 1, "check_interval_sec": 10.0}


class SpecError(ValueError):
    """The sweep spec (or something a trial needs from it) is invalid."""


def load_spec(path):
    with open(path) as f:
        return parse_spec(yaml.safe_load(f))


def parse_spec(data):
    """A validated, normalized copy of the sweep spec *data*."""
    if not isinstance(data, dict):
        raise SpecError("A sweep spec must be a YAML mapping")
    method = data.get("method")
    if method not in METHODS:
        raise SpecError(f"method must be one of {', '.join(METHODS)}, got {method!r}")
    spec = {
        "method": method,
        "metric": _metric(data.get("metric")),
        "parameters": _parameters(data.get("parameters"), method),
        "seed": int(data.get("seed", 0)),
    }
    if data.get("run_cap") is not None:
        spec["run_cap"] = _positive_int(data["run_cap"], "run_cap")
    if data.get("early_terminate") is not None:
        spec["early_terminate"] = _early_terminate(data["early_terminate"])
    for key in ("command", "program"):
        if data.get(key) is not None:
            spec[key] = data[key]
    if "command" in spec and not (
        isinstance(spec["command"], list) and all(isinstance(t, str) for t in spec["command"])
    ):
        raise SpecError("command must be a list of strings")
    return spec


def grid_values(param):
    """Every value a grid walks for one normalized *param*."""
    if "value" in param:
        return [param["value"]]
    if "values" in param:
        return list(param["values"])
    return list(range(param["min"], param["max"] + 1))  # int_uniform


def grid_size(spec):
    return math.prod(len(grid_values(p)) for p in spec["parameters"].values())


def trial_limit(spec):
    """How many trials the sweep runs at most; None when unbounded."""
    cap = spec.get("run_cap")
    if spec["method"] == "grid":
        size = grid_size(spec)
        return size if cap is None else min(size, cap)
    return cap


def _metric(metric):
    if not isinstance(metric, dict) or not metric.get("name"):
        raise SpecError("metric needs a name")
    goal = _GOALS.get(str(metric.get("goal", "minimize")).lower())
    if goal is None:
        raise SpecError(f"metric.goal must be minimize or maximize, got {metric.get('goal')!r}")
    return {"name": str(metric["name"]), "goal": goal}


def _parameters(parameters, method):
    if not isinstance(parameters, dict) or not parameters:
        raise SpecError("parameters must be a non-empty mapping")
    normalized = {}
    for name in sorted(parameters):
        normalized[name] = _parameter(str(name), parameters[name])
        if method == "grid" and not _discrete(normalized[name]):
            raise SpecError(
                f"grid needs discrete parameters; {name!r} is continuous "
                f"(use values: or int_uniform)"
            )
    return normalized


def _discrete(param):
    return "value" in param or "values" in param or param.get("distribution") == "int_uniform"


def _parameter(name, param):
    if not isinstance(param, dict):
        raise SpecError(f"parameter {name!r} must be a mapping (value:, values: or distribution:)")
    if "value" in param:
        return {"value": param["value"]}
    dist = param.get("distribution")
    if "values" in param or dist == "categorical":
        values = param.get("values")
        if not isinstance(values, list) or not values:
            raise SpecError(f"parameter {name!r}: values must be a non-empty list")
        return {"values": values}
    if dist is None and "min" in param and "max" in param:
        both_int = all(isinstance(param[k], int) for k in ("min", "max"))
        dist = "int_uniform" if both_int else "uniform"
    if dist not in DISTRIBUTIONS:
        raise SpecError(f"parameter {name!r}: unknown distribution {dist!r}")
    if dist == "normal":
        return {
            "distribution": dist,
            "mu": _number(param.get("mu", 0.0), name, "mu"),
            "sigma": _number(param.get("sigma", 1.0), name, "sigma"),
        }
    return _bounded(name, dist, param)


def _bounded(name, dist, param):
    if "min" not in param or "max" not in param:
        raise SpecError(f"parameter {name!r}: {dist} needs min and max")
    lo, hi = _number(param["min"], name, "min"), _number(param["max"], name, "max")
    if dist == "int_uniform":
        lo, hi = int(lo), int(hi)
    if lo > hi:
        raise SpecError(f"parameter {name!r}: min > max")
    if dist == "log_uniform" and lo <= 0:
        raise SpecError(f"parameter {name!r}: log_uniform needs min > 0")
    return {"distribution": dist, "min": lo, "max": hi}


def _number(value, name, field):
    try:
        number = float(value)  # PyYAML reads `1e-4` as a string
    except (TypeError, ValueError):
        raise SpecError(f"parameter {name!r}: {field} must be a number, got {value!r}")
    if not math.isfinite(number):
        raise SpecError(f"parameter {name!r}: {field} must be finite")
    return number


def _positive_int(value, field):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise SpecError(f"{field} must be a positive integer, got {value!r}")
    if number < 1:
        raise SpecError(f"{field} must be a positive integer, got {value!r}")
    return number


def _early_terminate(conf):
    if not isinstance(conf, dict) or conf.get("type") != "median":
        kind = conf.get("type") if isinstance(conf, dict) else conf
        raise SpecError(f"early_terminate.type must be median, got {kind!r}")
    merged = dict(_EARLY_TERMINATE_DEFAULTS, **{k: v for k, v in conf.items() if k != "type"})
    return {
        "type": "median",
        "min_iter": _positive_int(merged["min_iter"], "early_terminate.min_iter"),
        "min_trials": _positive_int(merged["min_trials"], "early_terminate.min_trials"),
        "check_interval_sec": float(merged["check_interval_sec"]),
    }
