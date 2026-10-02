"""Block codec of the metric stream (plan 12 §3.1)."""
import math
import random
import struct
import zlib

import pytest

from vmn_exp.core.metric_block import (
    MAGIC,
    decode_blocks,
    encode_block,
    intact_length,
    read_headers,
)
from vmn_exp.core.metric_columns import Columns

SPECIALS = [math.nan, math.inf, -math.inf]


def _random_columns(rng, n, has_step):
    steps = sorted(rng.sample(range(n * 5 + 1), n)) if has_step else None
    if steps is not None and rng.random() < 0.3:
        rng.shuffle(steps)  # lower explicit steps are kept, not reordered
    ts = [1_700_000_000_000_000 + i * rng.randint(0, 5000) for i in range(n)]
    values = [
        rng.choice(SPECIALS) if rng.random() < 0.05 else rng.uniform(-1e6, 1e6)
        for _ in range(n)
    ]
    return Columns(steps, ts, values)


def _random_keys(rng):
    return {
        f"k{i}": _random_columns(rng, rng.randint(1, 300), rng.random() < 0.7)
        for i in range(rng.randint(1, 6))
    }


def _same_float(a, b):
    return (math.isnan(a) and math.isnan(b)) or a == b


def _assert_equal(decoded, expected):
    assert list(decoded) == list(expected)
    for key, cols in expected.items():
        got = decoded[key]
        want_steps = None if cols.steps is None else list(cols.steps)
        assert (None if got.steps is None else list(got.steps)) == want_steps
        assert list(got.ts) == list(cols.ts)
        assert len(got.values) == len(cols.values)
        assert all(_same_float(a, b) for a, b in zip(got.values, cols.values))


@pytest.mark.parametrize("seed", range(25))
def test_round_trip_random_blocks(seed):
    rng = random.Random(seed)
    blocks = [_random_keys(rng) for _ in range(rng.randint(1, 4))]
    data = b"".join(encode_block(b, inherited=(i == 1)) for i, b in enumerate(blocks))
    decoded = list(decode_blocks(data))
    assert len(decoded) == len(blocks)
    for i, (block, expected) in enumerate(zip(decoded, blocks)):
        assert block.inherited is (i == 1)
        _assert_equal(block.keys, expected)


def test_empty_block_round_trips():
    (block,) = decode_blocks(encode_block({}))
    assert block.keys == {} and block.header["keys"] == []


def test_step_less_key_has_no_step_column():
    data = encode_block({"sys_cpu": Columns(None, [1, 2], [0.5, 0.7])})
    (header,) = read_headers(data)
    assert header["keys"][0]["has_step"] is False
    assert header["keys"][0]["s"] is None
    (block,) = decode_blocks(data)
    assert block.keys["sys_cpu"].steps is None
    assert list(block.keys["sys_cpu"].values) == [0.5, 0.7]


def test_layout_matches_spec():
    data = encode_block({"a": Columns([3], [7], [1.5])})
    assert data[:4] == MAGIC == b"VMSB" and data[4] == 1
    header_len, body_len, crc = struct.unpack("<III", data[5:17])
    assert len(data) == 17 + header_len + body_len
    assert crc == zlib.crc32(data[17:])
    body = zlib.decompress(data[17 + header_len :])
    assert struct.unpack("<qqd", body) == (3, 7, 1.5)


def test_one_million_points_one_key():
    n = 1_000_000
    cols = Columns(list(range(n)), list(range(0, 2 * n, 2)), [i * 0.5 for i in range(n)])
    data = encode_block({"loss": cols})
    assert len(data) < n * 8  # deltas compress
    (block,) = decode_blocks(data)
    got = block.keys["loss"]
    assert len(got.values) == n
    assert (got.steps[-1], got.ts[-1], got.values[-1]) == (n - 1, 2 * n - 2, (n - 1) * 0.5)


@pytest.mark.parametrize("cut", [1, 5, 16, 30, -1])
def test_torn_tail_is_ignored(cut):
    first = encode_block({"a": Columns([1], [1], [1.0])})
    second = encode_block({"a": Columns([2, 3], [2, 3], [2.0, 3.0])})
    torn = first + second[: cut if cut > 0 else len(second) + cut]
    assert [list(b.keys["a"].steps) for b in decode_blocks(torn)] == [[1]]
    assert len(list(read_headers(torn))) == 1
    assert intact_length(torn) == len(first)


def test_bad_crc_tail_is_ignored():
    first = encode_block({"a": Columns([1], [1], [1.0])})
    second = bytearray(encode_block({"a": Columns([2], [2], [2.0])}))
    second[-1] ^= 0xFF
    data = first + bytes(second)
    assert len(list(decode_blocks(data))) == 1
    assert len(list(read_headers(data))) == 1
    assert intact_length(data) == len(first)


def test_reads_from_a_binary_stream(tmp_path):
    path = tmp_path / "w.vms"
    path.write_bytes(encode_block({"a": Columns([1], [1], [1.0])}) + b"VMS")
    with open(path, "rb") as f:
        assert len(list(decode_blocks(f))) == 1


def _brute_summary(cols):
    steps = cols.steps if cols.steps is not None else [None] * len(cols.ts)
    pts = list(zip(steps, cols.ts, cols.values))
    finite = [p for p in pts if math.isfinite(p[2])]

    def triple(p):
        return [p[2], p[0], p[1]]

    summ = {"n": len(finite), "sum": math.fsum(p[2] for p in finite)}
    summ["min"] = triple(min(finite, key=lambda p: p[2])) if finite else None
    summ["max"] = triple(max(finite, key=lambda p: p[2])) if finite else None
    return pts, summ


@pytest.mark.parametrize("seed", range(15))
def test_header_summaries_equal_brute_force_fold(seed):
    rng = random.Random(100 + seed)
    keys = _random_keys(rng)
    (header,) = read_headers(encode_block(keys))
    for entry in header["keys"]:
        cols = keys[entry["k"]]
        pts, summ = _brute_summary(cols)
        assert entry["n"] == len(pts)
        assert entry["t"] == [pts[0][1], pts[-1][1]]
        if cols.steps is not None:
            assert entry["s"] == [pts[0][0], pts[-1][0]]
        got = entry["sum"]
        assert got["n"] == summ["n"] and got["sum"] == pytest.approx(summ["sum"])
        assert got["min"] == summ["min"] and got["max"] == summ["max"]
        for name, p in (("first", pts[0]), ("last", pts[-1])):
            v, s, t = entry[name]
            assert _same_float(v, p[2]) and (s, t) == (p[0], p[1])
