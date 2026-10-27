"""A packed ``metric_summary``: what the index keeps per run instead of a dict
of dicts, read back exactly as it was."""
import json
import math
import pickle

from vmn_exp.core.metric_pack import PackedSummary
from vmn_exp.core.metric_summary import with_policies

SUMMARY = {
    "loss": {"last": 0.25, "min": 0.1, "max": 0.9, "first": 0.9, "mean": 0.4},
    "epoch": {"last": 3, "min": 1, "max": 3, "first": 1, "mean": 2.0},
    "nan_last": {"last": float("nan"), "min": 1.0, "max": 2.0, "first": float("inf"), "mean": 1.5},
    "no_finite": {"last": float("nan"), "min": None, "max": None, "first": float("nan"),
                  "mean": None},
    "huge": {"last": 2 ** 60, "min": True, "max": "odd", "first": -0.0, "mean": 1e308},
}


def _same(a, b):
    """Equal, NaN included, and of the same type."""
    if isinstance(a, float) and math.isnan(a):
        return isinstance(b, float) and math.isnan(b)
    return type(a) is type(b) and a == b and str(a) == str(b)


def test_it_reads_back_every_value_exactly():
    packed = PackedSummary.of(SUMMARY)
    unpacked = packed.to_dict()
    assert list(unpacked) == list(SUMMARY)
    for name, seen in SUMMARY.items():
        assert list(unpacked[name]) == list(seen)
        for field, value in seen.items():
            assert _same(unpacked[name][field], value), (name, field)


def test_it_reads_like_the_dict_it_packs():
    packed = PackedSummary.of(SUMMARY)
    assert len(packed) == len(SUMMARY) and "loss" in packed and "x" not in packed
    assert dict(packed.items())["loss"] == SUMMARY["loss"]
    assert packed.get("epoch") == SUMMARY["epoch"] and packed.get("x") is None
    assert with_policies({"loss": 0.25}, packed, {"loss": {"goal": "min"}}, None)["loss"] == 0.1


def test_it_round_trips_through_json_and_pickle():
    packed = PackedSummary.of(SUMMARY)
    again = PackedSummary.of(json.loads(json.dumps(packed.to_dict())))
    assert json.dumps(again.to_dict()) == json.dumps(packed.to_dict())
    pickled = pickle.loads(pickle.dumps(packed))
    assert json.dumps(pickled.to_dict()) == json.dumps(packed.to_dict())


def test_an_empty_summary_packs_to_none():
    assert PackedSummary.of({}) is None
