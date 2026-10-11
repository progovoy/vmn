"""Conf weights (``experiment.similar.weights``) too large for a float are
ignored like any other invalid weight, never an OverflowError."""
import pytest
from vmn_exp.core.similar_score import DEFAULT_WEIGHTS, resolve_weights


@pytest.mark.parametrize("huge", [10 ** 400, -(10 ** 400)], ids=["huge", "huge_negative"])
def test_a_weight_too_large_for_a_float_is_ignored(huge):
    assert resolve_weights({"code": huge}) == DEFAULT_WEIGHTS


def test_a_large_int_weight_that_fits_a_float_still_counts():
    assert resolve_weights({"code": 10 ** 20})["code"] == float(10 ** 20)
