"""Indexed metric file (plan 12 §3.2): raw chunks, LOD pyramid, footer."""
import json
import math
import random
import struct
import zlib

import pytest

from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_index_file import (
    CHUNK_POINTS,
    LOD_SIZES,
    MAGIC,
    MetricIndexReader,
    build_index,
)
from vmn_exp.core.metric_lod import decode_buckets
from vmn_exp.ui.readers.series import SeriesThinner, downsample


def _reader(data, log=None):
    def read_range(offset, length):
        if log is not None:
            log.append((offset, length))
        return data[offset : offset + length]

    return MetricIndexReader(read_range, len(data))


def _wave(n, seed=0, step0=0, specials=True):
    rng = random.Random(seed)
    values = []
    for i in range(n):
        if specials and rng.random() < 0.01:
            values.append(rng.choice([math.nan, math.inf, -math.inf]))
        else:
            values.append(math.sin(i / 50) + rng.uniform(-0.2, 0.2))
    return Columns(list(range(step0, step0 + 3 * n, 3)), [10 * i for i in range(n)], values)


def _points(cols):
    steps = cols.steps if cols.steps is not None else [None] * len(cols.ts)
    return [
        {"step": s, "value": v, "ts": t} for s, t, v in zip(steps, cols.ts, cols.values)
    ]


def _same(a, b):
    assert len(a) == len(b)
    for p, q in zip(a, b):
        assert (p["step"], p["ts"]) == (q["step"], q["ts"])
        assert (math.isnan(p["value"]) and math.isnan(q["value"])) or p["value"] == q["value"]


def test_layout_and_footer_read_from_the_end():
    data = build_index("w1", {"loss": _wave(100)})
    assert data[:4] == MAGIC == b"VMSX" and data[4] == 1 and data[-4:] == MAGIC
    footer_len, crc = struct.unpack("<II", data[-12:-4])
    raw = data[-12 - footer_len : -12]
    assert zlib.crc32(raw) == crc
    footer = json.loads(zlib.decompress(raw))
    assert footer["writer"] == "w1" and footer["rows"] == 100 and footer["format"] == 1
    log = []
    reader = _reader(data, log)
    assert reader.footer == footer
    assert all(off + length == len(data) for off, length in log)


@pytest.mark.parametrize("seed", range(6))
def test_round_trip_random_keys(seed):
    rng = random.Random(seed)
    keys = {}
    for i in range(rng.randint(1, 4)):
        n = rng.randint(1, 3000)
        cols = _wave(n, seed=seed + i, step0=rng.randint(-5, 5))
        if rng.random() < 0.3:
            cols = Columns(None, cols.ts, cols.values)
        keys[f"k{i}"] = cols
    reader = _reader(build_index("w", keys))
    assert sorted(reader.keys()) == sorted(keys)
    for key, cols in keys.items():
        _same(reader.points(key), _points(cols))
        assert reader.footer["keys"][key]["n"] == len(cols.ts)


def test_empty_index():
    reader = _reader(build_index("w", {}))
    assert reader.keys() == [] and reader.footer["rows"] == 0


def test_points_are_sorted_by_step():
    cols = Columns([5, 1, 3], [1, 2, 3], [5.0, 1.0, 3.0])
    reader = _reader(build_index("w", {"a": cols}))
    assert [p["step"] for p in reader.points("a")] == [1, 3, 5]


def test_step_range_reads_only_the_needed_chunks():
    n = 3 * CHUNK_POINTS + 10
    cols = _wave(n, specials=False)
    data = build_index("w", {"loss": cols})
    log = []
    reader = _reader(data, log)
    log.clear()
    lo, hi = cols.steps[CHUNK_POINTS + 5], cols.steps[CHUNK_POINTS + 50]
    got = reader.points("loss", lo, hi)
    _same(got, _points(cols)[CHUNK_POINTS + 5 : CHUNK_POINTS + 51])
    assert len(log) == 3  # one chunk per column


def test_lod_levels_need_two_buckets():
    reader = _reader(build_index("w", {"a": _wave(64 * 3 + 2), "b": _wave(64 + 2)}))
    assert list(reader.footer["keys"]["a"]["lod"]) == ["64"]
    assert reader.footer["keys"]["b"]["lod"] == {}
    big = _reader(build_index("w", {"a": _wave(1024 * 2 + 2)}))
    assert list(big.footer["keys"]["a"]["lod"]) == ["64", "1024"]
    assert LOD_SIZES == (64, 1024, 16384, 262144)


def _thinner_buckets(points, size):
    """The (lo, hi) positions SeriesThinner keeps once its buckets span *size*."""
    n = len(points)
    n_buckets = -(-(n - 2) // size)
    thinner = SeriesThinner(2 * n_buckets + 2)
    thinner.thin(points, n)
    assert thinner._size == size
    return thinner._buckets


@pytest.mark.parametrize("size", [64, 1024])
def test_lod_buckets_equal_series_thinner_buckets(size):
    n = size * 37 + 11
    cols = _wave(n, seed=size)
    points = _points(cols)
    data = build_index("w", {"loss": cols})
    lod = _reader(data).footer["keys"]["loss"]["lod"][str(size)]
    buckets = decode_buckets(data[lod["off"] : lod["off"] + lod["len"]])  # alone
    expected = _thinner_buckets(points, size)
    assert len(buckets) == len(expected) == lod["buckets"]
    for bucket, (lo, hi) in zip(buckets, expected):
        if lo is None:
            assert bucket.n_finite == 0
            continue
        assert (bucket.min_v, bucket.min_step, bucket.min_ts) == (
            points[lo]["value"], points[lo]["step"], points[lo]["ts"])
        assert (bucket.max_v, bucket.max_step, bucket.max_ts) == (
            points[hi]["value"], points[hi]["step"], points[hi]["ts"])


def test_bucket_sums_count_finite_values():
    n = 64 * 4 + 2
    cols = _wave(n, seed=3)
    data = build_index("w", {"loss": cols})
    lod = _reader(data).footer["keys"]["loss"]["lod"]["64"]
    buckets = decode_buckets(data[lod["off"] : lod["off"] + lod["len"]])
    for k, bucket in enumerate(buckets):
        vals = [v for v in cols.values[1 + 64 * k : 1 + 64 * (k + 1)] if math.isfinite(v)]
        assert bucket.n_finite == len(vals)
        assert bucket.sum == pytest.approx(math.fsum(vals))


def test_series_matches_downsample_when_levels_agree():
    n = 64 * 500 + 7
    cols = _wave(n, seed=9)
    points = _points(cols)
    reader = _reader(build_index("w", {"loss": cols}))
    max_points = 2 * 501 + 2  # the thinner settles on 64-point buckets too
    _same(reader.series("loss", max_points, level=64), downsample(points, max_points))


def test_series_respects_max_points_and_keeps_extremes():
    n = 200_000
    cols = _wave(n, seed=4, specials=False)
    cols.values[123_457] = 99.0
    reader = _reader(build_index("w", {"loss": cols}))
    got = reader.series("loss", 2000)
    assert len(got) <= 2000 + 4
    assert got[0]["step"] == cols.steps[0] and got[-1]["step"] == cols.steps[-1]
    assert max(p["value"] for p in got) == 99.0
    steps = [p["step"] for p in got]
    assert steps == sorted(steps)


def test_series_over_a_range():
    n = 100_000
    cols = _wave(n, seed=5, specials=False)
    cols.values[50_001] = -50.0
    reader = _reader(build_index("w", {"loss": cols}))
    lo, hi = cols.steps[40_000], cols.steps[60_000]
    got = reader.series("loss", 500, lo, hi)
    assert got[0]["step"] == lo and got[-1]["step"] == hi
    assert all(lo <= p["step"] <= hi for p in got)
    assert min(p["value"] for p in got) == -50.0
    assert len(got) <= 500 + 4


def test_small_range_returns_raw_points():
    cols = _wave(5000, seed=6)
    reader = _reader(build_index("w", {"loss": cols}))
    lo, hi = cols.steps[100], cols.steps[300]
    _same(reader.series("loss", 2000, lo, hi), _points(cols)[100:301])


def test_one_million_points_round_trip():
    n = 1_000_000
    cols = Columns(list(range(n)), list(range(n)), [float(i % 977) for i in range(n)])
    data = build_index("w", {"loss": cols})
    reader = _reader(data)
    assert list(reader.footer["keys"]["loss"]["lod"]) == ["64", "1024", "16384", "262144"]
    tail = reader.points("loss", n - 3, n - 1)
    assert [p["value"] for p in tail] == [float(i % 977) for i in range(n - 3, n)]
    assert len(reader.series("loss", 2000)) <= 2004
