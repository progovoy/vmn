"""Thinning a growing series costs its new points, with the same result as
thinning the whole series again."""
import random

from version_stamp.ui.readers import series as series_mod
from version_stamp.ui.readers.series import SeriesThinner, downsample


def _points(n, seed=0):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        value = rng.choice([rng.random(), rng.random() * 100, None, float("nan")])
        out.append({"step": i, "ts": str(i), "value": value})
    return out


def test_incremental_thinning_equals_a_full_thinning():
    points = _points(30_000)
    thinner = SeriesThinner(max_points=200)
    rng = random.Random(1)
    count = 0
    while count < len(points):
        count = min(len(points), count + rng.choice([1, 3, 50, 700, 4000]))
        assert thinner.thin(points, count) == downsample(points[:count], 200), count


def test_thinning_keeps_the_contract():
    points = [{"step": i, "ts": "t", "value": 100.0 if i == 777 else 1.0} for i in range(10_000)]
    for max_points in (2, 3, 10, 101, 2000):
        thinned = downsample(points, max_points)
        assert len(thinned) <= max(max_points, 2)
        assert thinned[0] is points[0] and thinned[-1] is points[-1]
        steps = [p["step"] for p in thinned]
        assert steps == sorted(steps)
    assert any(p["value"] == 100.0 for p in downsample(points, 100))
    assert downsample(points[:50], 100) == points[:50]


def test_a_grown_series_reads_only_its_new_points(monkeypatch):
    points = _points(50_000, seed=3)
    thinner = SeriesThinner(max_points=500)
    thinner.thin(points, 40_000)

    seen = []
    real = series_mod._summarize

    def counting(bucket):
        seen.append(len(bucket))
        return real(bucket)

    monkeypatch.setattr(series_mod, "_summarize", counting)
    thinner.thin(points, 40_010)
    assert sum(seen) < 2_000  # the open buckets, not the 40k-point series


def test_an_older_count_is_thinned_from_scratch():
    points = _points(5_000, seed=4)
    thinner = SeriesThinner(max_points=100)
    thinner.thin(points, 5_000)
    assert thinner.thin(points, 1_000) == downsample(points[:1_000], 100)
