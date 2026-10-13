"""Plan 23 S1: the job rollup's quantile sketch — mergeable, removable,
about 1% relative accuracy, small."""
import math
import random

import pytest
from vmn_exp.ui.quantile_sketch import QuantileSketch


def _exact(values, q):
    ordered = sorted(values)
    return ordered[round(q * (len(ordered) - 1))]


def _close(got, want, rel=0.011):
    return abs(got - want) <= rel * abs(want) + 1e-12


@pytest.mark.parametrize("draw", [
    lambda rng: rng.lognormvariate(0, 1),
    lambda rng: rng.uniform(-5, 5),
    lambda rng: -rng.expovariate(3),
    lambda rng: rng.choice([0.0, 0.0, 1.0, rng.random()]),
])
def test_quantiles_are_within_one_percent_of_the_exact_ranks(draw):
    rng = random.Random(1)
    values = [draw(rng) for _ in range(5000)]
    sketch = QuantileSketch()
    for value in values:
        sketch.add(value)
    assert sketch.count == len(values)
    for q in (0.0, 0.1, 0.5, 0.9, 0.99, 1.0):
        assert _close(sketch.quantile(q), _exact(values, q)), q


def test_an_empty_sketch_has_no_quantile_or_histogram():
    sketch = QuantileSketch()
    assert sketch.count == 0
    assert sketch.quantile(0.5) is None
    assert sketch.histogram(bins=8) == []


def test_non_finite_and_non_numeric_values_are_ignored():
    sketch = QuantileSketch()
    for value in (float("nan"), float("inf"), -float("inf"), None, "x", True):
        sketch.add(value)
    assert sketch.count == 0
    sketch.add(2.0)
    assert sketch.count == 1 and _close(sketch.quantile(0.5), 2.0)


def test_removing_values_undoes_adding_them():
    rng = random.Random(2)
    kept = [rng.lognormvariate(0, 1) for _ in range(300)]
    gone = [rng.uniform(-3, 3) for _ in range(300)] + [0.0] * 5
    sketch, fresh = QuantileSketch(), QuantileSketch()
    for value in kept + gone:
        sketch.add(value)
    for value in gone:
        sketch.add(value, by=-1)
    for value in kept:
        fresh.add(value)
    assert sketch == fresh


def test_merge_equals_adding_everything_to_one():
    rng = random.Random(3)
    left = [rng.gauss(0, 10) for _ in range(500)]
    right = [rng.gauss(5, 1) for _ in range(500)]
    a, b, both = QuantileSketch(), QuantileSketch(), QuantileSketch()
    for value in left:
        a.add(value)
        both.add(value)
    for value in right:
        b.add(value)
        both.add(value)
    merged = a.copy()
    merged.merge(b)
    assert merged == both
    assert a.count == 500  # copy() is independent
    merged.merge(b, by=-1)
    assert merged == a


def test_the_bins_stay_bounded_however_wide_the_values():
    sketch = QuantileSketch()
    for exponent in range(-1000, 1000):
        sketch.add(1.5 ** exponent)
        sketch.add(-(1.5 ** exponent))
    assert sketch.bins() <= 2 * QuantileSketch.MAX_BINS
    assert sketch.count == 4000
    # The top of the range keeps its accuracy; the collapsed tail is the small end.
    assert _close(sketch.quantile(1.0), 1.5 ** 999)
    assert _close(sketch.quantile(0.0), -(1.5 ** 999))


def test_histogram_bins_cover_the_range_and_hold_every_count():
    rng = random.Random(4)
    values = [rng.uniform(0, 100) for _ in range(1000)]
    sketch = QuantileSketch()
    for value in values:
        sketch.add(value)
    hist = sketch.histogram(bins=10, lo=min(values), hi=max(values))
    assert len(hist) == 10
    assert sum(b["count"] for b in hist) == 1000
    assert hist[0]["lo"] == min(values) and hist[-1]["hi"] == max(values)
    assert all(a["hi"] == b["lo"] for a, b in zip(hist, hist[1:]))
    exact = [sum(1 for v in values if b["lo"] <= v < b["hi"]) for b in hist]
    assert all(abs(got["count"] - want) <= 30 for got, want in zip(hist, exact))


def test_a_single_value_histogram_is_one_bin():
    sketch = QuantileSketch()
    for _ in range(3):
        sketch.add(0.5)
    hist = sketch.histogram(bins=10)
    assert len(hist) == 1 and hist[0]["count"] == 3
    assert math.isclose(hist[0]["lo"], 0.5, rel_tol=0.011)
