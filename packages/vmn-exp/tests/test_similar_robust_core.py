"""Similar runs never break on odd values (vmn_exp.core.similar_*): params
far apart or non-finite, conf weights of the wrong shape, an intent that is
not a mapping, and a target that names its own app among several."""
import logging

import pytest
from similar_fixtures import FakeSnapshot, explain, run, similar_runs, similar_runs_multi
from vmn_exp.core.similar import target_from_snapshot
from vmn_exp.core.similar_profile import build_profile, document_text, keyword_phrases
from vmn_exp.core.similar_weights import DEFAULT_WEIGHTS, resolve_weights

NAN, INF = float("nan"), float("inf")


def test_a_query_with_extreme_params_explains_instead_of_raising():
    a = {"row": run("a", params={"lr": 1e-200, "seed": 10 ** 400, "x": NAN})}
    b = {"row": run("b", params={"lr": 1e200, "seed": 1, "x": NAN})}
    reasons, signals = explain(a, b)
    assert 0 < signals["params"] < 1
    assert reasons[0] == "same base commit aaaaaaa"


@pytest.mark.parametrize("overrides", [[1, 2], ["code"], 3, "params", 2.5, True,
                                       (("code", 1),)])
def test_weights_that_are_not_a_mapping_are_ignored(overrides, caplog):
    with caplog.at_level(logging.DEBUG, logger="vmn_exp.core.similar_weights"):
        assert resolve_weights(overrides) == DEFAULT_WEIGHTS
    assert "experiment.similar.weights" in caplog.text


def test_a_search_takes_weights_of_the_wrong_shape_as_the_defaults():
    rows = [run("a", params={"opt": "adam"}), run("b", params={"opt": "sgd"})]
    snap = FakeSnapshot(rows)
    target = target_from_snapshot(snap, "a")
    assert similar_runs(snap, target, weights=[1, 2]) == similar_runs(snap, target)


def test_non_numeric_negative_and_non_finite_weight_values_are_ignored():
    weights = resolve_weights({"code": NAN, "files": INF, "params": -2, "text": "3",
                               "symbols": None, "inputs": [1], "branch": 0})
    assert weights == dict(DEFAULT_WEIGHTS, branch=0.0)


@pytest.mark.parametrize("intent", [["focal", "loss"], "focal loss", 3, ("focal",)])
def test_an_intent_that_is_not_a_mapping_reads_as_none(intent):
    row = run("a", name="focal sweep")
    assert keyword_phrases(intent) == []
    assert document_text(row, intent=intent) == document_text(row)
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
