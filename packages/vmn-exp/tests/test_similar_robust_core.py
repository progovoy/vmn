"""Similar runs never break on odd values (vmn_exp.core.similar_*): params
far apart or non-finite, conf weights of the wrong shape, an intent that is
not a mapping, and a target that names its own app among several."""
import logging

import pytest
from similar_fixtures import FakeSnapshot, run
from vmn_exp.core.similar import similar_runs_multi, target_from_snapshot
from vmn_exp.core.similar_profile import build_profile
from vmn_exp.core.similar_score import (
    DEFAULT_WEIGHTS,
    resolve_weights,
    score,
    value_closeness,
)
from vmn_exp.core.similar_text import document_terms, keyword_phrases

NAN, INF = float("nan"), float("inf")


@pytest.mark.parametrize("a, b", [(1e-200, 1e200), (1e200, 1e-200), (1e-308, 1e308),
                                  (2.2e-308, 1e17), (5e-324, 1.0)])
def test_positive_params_whose_ratio_underflows_or_overflows_are_not_close(a, b):
    assert value_closeness(a, b) == 0.0


@pytest.mark.parametrize("a, b", [(NAN, NAN), (INF, INF), (-INF, -INF), (NAN, 1.0),
                                  (1.0, INF), ("inf", "inf"), ("nan", "nan")])
def test_non_finite_values_are_not_comparable(a, b):
    assert value_closeness(a, b) == 0.0


def test_a_query_with_extreme_params_scores_instead_of_raising():
    a = {"row": run("a", params={"lr": 1e-200, "seed": 10 ** 400, "x": NAN})}
    b = {"row": run("b", params={"lr": 1e200, "seed": 1, "x": NAN})}
    total, reasons, signals = score(a, b)
    assert signals["params"] == 0.0
    assert 0 < total < 1 and reasons == ["same base commit aaaaaaa"]


def test_a_huge_integer_param_reads_as_text_in_a_reason():
    a = {"row": {"verstr": "a", "params": {"seed": 1, "lr": 0.1}}}
    b = {"row": {"verstr": "b", "params": {"seed": 10 ** 30, "lr": 0.1}}}
    assert score(a, b)[1] == ["seed 1e30 vs 1"]
    huge = {"row": {"verstr": "c", "params": {"seed": 10 ** 400, "lr": 0.1}}}
    (reason,) = score(a, huge)[1]
    assert reason.startswith("seed 1000") and reason.endswith("… vs 1")


@pytest.mark.parametrize("overrides", [[1, 2], ["code"], 3, "params", 2.5, True,
                                       (("code", 1),)])
def test_weights_that_are_not_a_mapping_are_ignored(overrides, caplog):
    with caplog.at_level(logging.DEBUG, logger="vmn_exp.core.similar_score"):
        assert resolve_weights(overrides) == DEFAULT_WEIGHTS
    assert "experiment.similar.weights" in caplog.text


def test_score_takes_weights_of_the_wrong_shape_as_the_defaults():
    a, b = {"row": run("a", params={"opt": "adam"})}, {"row": run("b", params={"opt": "sgd"})}
    assert score(a, b, weights=[1, 2]) == score(a, b)


def test_non_numeric_negative_and_non_finite_weight_values_are_ignored():
    weights = resolve_weights({"code": NAN, "files": INF, "params": -2, "text": "3",
                               "symbols": None, "inputs": [1], "branch": 0})
    assert weights == dict(DEFAULT_WEIGHTS, branch=0.0)


@pytest.mark.parametrize("intent", [["focal", "loss"], "focal loss", 3, ("focal",)])
def test_an_intent_that_is_not_a_mapping_reads_as_none(intent):
    row = run("a", name="focal sweep")
    assert keyword_phrases(intent) == []
    assert document_terms(row, intent=intent) == document_terms(row)
    profile = build_profile(row, intent=intent)
    assert profile.has_intent is False and profile.keywords == ()


def test_similar_runs_survive_a_snapshot_whose_intent_is_a_list():
    rows = [run("t", params={"lr": 0.1}), run("u", params={"lr": 0.1})]
    snapshot = FakeSnapshot(rows, intents={"t": ["x"], "u": "y"})
    target = target_from_snapshot(snapshot, "t")
    items = similar_runs_multi([("app", snapshot, None)], target)
    assert [i["verstr"] for i in items] == ["u"]


def _two_apps_sharing_one_code():
    code = run("t")["code_verstr"]
    first = FakeSnapshot([run("t", params={"lr": 0.1}),
                          run("repeat", code=code, params={"lr": 0.1})])
    second = FakeSnapshot([run("u", code=code, params={"lr": 0.1})])
    return first, second


def test_a_target_names_its_app_when_asked():
    first, _ = _two_apps_sharing_one_code()
    assert target_from_snapshot(first, "t", app="a")["app"] == "a"
    assert "app" not in target_from_snapshot(first, "t")


def test_exclusions_apply_only_in_the_targets_own_app():
    first, second = _two_apps_sharing_one_code()
    target = target_from_snapshot(first, "t", app="a")
    items = similar_runs_multi([("a", first, None), ("b", second, None)], target)
    assert [(i["app"], i["verstr"]) for i in items] == [("b", "u")]
