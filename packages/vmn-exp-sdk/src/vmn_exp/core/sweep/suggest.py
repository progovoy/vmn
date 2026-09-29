"""A trial's params, from its index: grid point, seeded random draw, or TPE.

Grid and random are pure functions of (spec, trial index), so any agent
anywhere computes the same params for a slot. Bayes also depends on the
finished trials so far (*history*); the claim records what it drew.
"""
import hashlib
import itertools
import math
import random

from vmn_exp.core.sweep.spec import grid_values


def suggest(spec, n, history=()):
    """Params for trial *n*; *history* is ``[(params, value)]`` (bayes only)."""
    method = spec["method"]
    if method == "grid":
        return grid_point(spec, n)
    if method == "random":
        return random_point(spec, n)
    return bayes_point(spec, n, history)


def grid_point(spec, n):
    """The *n*-th point of the grid (first parameter varies slowest), or None."""
    names = list(spec["parameters"])
    axes = [grid_values(spec["parameters"][name]) for name in names]
    point = next(itertools.islice(itertools.product(*axes), n, None), None)
    return None if point is None else dict(zip(names, point))


def random_point(spec, n):
    rng = random.Random(trial_seed(spec, n))
    return {name: _draw(rng, param) for name, param in spec["parameters"].items()}


def bayes_point(spec, n, history):
    from vmn_exp.integrations.optuna_study import suggest_params

    return suggest_params(spec["parameters"], spec["metric"]["goal"], history,
                          seed=trial_seed(spec, n))


def trial_seed(spec, n):
    """A stable 64-bit seed for trial *n* (``hash()`` is salted per process)."""
    digest = hashlib.sha256(f"{spec.get('seed', 0)}:{n}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _draw(rng, param):
    if "value" in param:
        return param["value"]
    if "values" in param:
        return rng.choice(param["values"])
    dist = param["distribution"]
    if dist == "int_uniform":
        return rng.randint(param["min"], param["max"])
    if dist == "uniform":
        return rng.uniform(param["min"], param["max"])
    if dist == "log_uniform":
        drawn = math.exp(rng.uniform(math.log(param["min"]), math.log(param["max"])))
        return min(max(drawn, param["min"]), param["max"])  # exp(log(x)) may round past x
    return rng.gauss(param["mu"], param["sigma"])  # normal
