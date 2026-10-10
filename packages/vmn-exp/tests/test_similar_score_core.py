"""Pairwise similarity of two runs (vmn_exp.core.similar_score): one value in
[0, 1] per signal, a weighted mean over the signals both runs carry, and the
reasons a human reads."""
import math

import pytest
from similar_fixtures import changed, dataset, run
from vmn_exp.core.similar_score import DEFAULT_WEIGHTS, SIGNALS, resolve_weights, score

# A row with nothing but what a test gives it: no code, params or metrics.
BARE = {"verstr": "x", "code_verstr": "0.0.0-mlflow.x"}


def _view(row=None, features=None, **extra):
    return {"row": dict(BARE, **(row or {})), "features": features, **extra}


def _signals(a, b, **kw):
    return score(a, b, **kw)[2]


def test_every_signal_has_a_positive_default_weight():
    assert set(DEFAULT_WEIGHTS) == set(SIGNALS)
    assert DEFAULT_WEIGHTS["symbols"] > DEFAULT_WEIGHTS["files"]
    assert all(w > 0 for w in DEFAULT_WEIGHTS.values())


def test_the_same_base_commit_is_full_code_similarity():
    total, reasons, signals = score({"row": run("a")}, {"row": run("b")})
    assert signals == {"code": 1.0}
    assert total == 1.0
    assert reasons == ["same base commit aaaaaaa"]


def test_the_same_base_version_on_another_commit_is_seven_tenths():
    _, reasons, signals = score({"row": run("a")}, {"row": run("b", commit="bbbbbbb")})
    assert signals["code"] == pytest.approx(0.7)
    assert reasons == ["same base version 1.0.0"]


def test_code_similarity_decays_with_version_distance():
    def code(base):
        return _signals({"row": run("a")}, {"row": run("b", commit="bbbbbbb", base=base)})["code"]

    near = [code(b) for b in ("1.0.1", "1.0.3", "1.1.0", "1.3.0", "2.0.0", "5.0.0")]
    assert 0.7 > near[0]
    assert near == sorted(near, reverse=True) and len(set(near)) == len(near)
    assert near[-1] > 0


def test_an_imported_source_commit_matches_a_dev_verstr_commit():
    imported = _view({"imported_from": {"source_commit": "aaaaaaa0123456789"}})
    assert _signals({"row": run("a")}, imported)["code"] == 1.0


def test_files_and_symbols_are_jaccard_similarities():
    a = changed(files=["src/a.py", "src/b.py"], symbols=["src/a.py::f", "src/b.py::g"])
    b = changed(files=["src/b.py", "src/c.py"], symbols=["src/b.py::g"])
    signals = _signals(_view(features=a), _view(features=b))
    assert signals["files"] == pytest.approx(1 / 3)
    assert signals["symbols"] == pytest.approx(1 / 2)


def test_shared_functions_are_named_by_file_name_and_function():
    features = changed(symbols=["src/loss.py::focal_loss", "src/train.py::train_step"])
    _, reasons, _ = score(_view(features=features), _view(features=features))
    assert reasons == ["2 shared functions: loss.py::focal_loss, train.py::train_step"]


def test_shared_files_list_three_then_an_ellipsis():
    features = changed(files=["d.py", "c.py", "b.py", "a.py"])
    _, reasons, _ = score(_view(features=features), _view(features=features))
    assert reasons == ["4 shared files: a.py, b.py, c.py, …"]


def test_untracked_files_count_as_changed_files():
    a = {"changed": {"files": ["a.py"], "untracked": ["new.py"]}}
    b = changed(files=["new.py"])
    assert _signals(_view(features=a), _view(features=b))["files"] == pytest.approx(1 / 2)


def test_commit_derived_changes_weigh_half():
    files = changed(files=["a.py"])
    commit_files = dict(changed(files=["a.py"]), changed_source="commit")
    params = {"params": {"opt": "adam"}}
    other = {"params": {"opt": "sgd"}}
    full = score(_view(params, files), _view(other, files))[0]
    half = score(_view(params, files), _view(other, commit_files))[0]
    w_files, w_params = DEFAULT_WEIGHTS["files"], DEFAULT_WEIGHTS["params"]
    assert full == pytest.approx(w_files / (w_files + w_params))
    assert half == pytest.approx(w_files / 2 / (w_files / 2 + w_params))


def test_the_same_input_digest_is_full_similarity_and_names_the_dataset():
    a = _view({"inputs": dataset("imagenet@3", "sha256:1")})
    b = _view({"inputs": dataset("imagenet@3", "sha256:1")})
    total, reasons, signals = score(a, b)
    assert signals == {"inputs": 1.0}
    assert reasons == ["same dataset imagenet@3"]


def test_another_version_of_the_same_dataset_is_six_tenths():
    a = _view({"inputs": dataset("imagenet@3", "sha256:1")})
    b = _view({"inputs": dataset("imagenet@4", "sha256:2")})
    _, reasons, signals = score(a, b)
    assert signals["inputs"] == pytest.approx(0.6)
    assert reasons == ["dataset imagenet@4 vs imagenet@3"]


def test_params_are_key_jaccard_times_mean_value_closeness():
    a = _view({"params": {"lr": 1e-4, "bs": 32}})
    b = _view({"params": {"lr": 3e-4, "bs": 32, "opt": "adam"}})
    _, reasons, signals = score(a, b)
    closeness = 1 - abs(math.log10(3)) / 2
    assert signals["params"] == pytest.approx(2 / 3 * (closeness + 1) / 2)
    assert reasons == ["lr 3e-4 vs 1e-4"]


def test_params_far_apart_or_of_other_kinds_compare_by_equality():
    a = _view({"params": {"lr": 1.0, "momentum": 0, "opt": "adam", "flag": True}})
    b = _view({"params": {"lr": 1000.0, "momentum": 0, "opt": "sgd", "flag": 1}})
    assert _signals(a, b)["params"] == pytest.approx(1 / 4)


def test_identical_params_are_named_in_the_reason():
    params = {"params": {"lr": 0.1, "epochs": 3}}
    assert score(_view(params), _view(params))[1] == ["same params: epochs, lr"]


@pytest.mark.parametrize("other, expected", [
    (["python", "train.py", "fit", "--lr", "2"], 1.0),
    (["python3", "-u", "train.py", "fit"], 1.0),
    (["python", "train.py", "eval"], 0.7),
    (["python", "eval.py", "fit"], 0.0),
])
def test_the_entrypoint_is_the_script_then_its_subcommand(other, expected):
    target = _view(command=["python", "train.py", "fit", "--lr", "1"])
    assert _signals(target, _view(command=other))["entrypoint"] == pytest.approx(expected)


def test_a_features_entrypoint_stands_in_for_a_missing_command():
    target = _view(command=["torchrun", "--nproc_per_node", "8", "src/train.py"])
    imported = _view(features={"entrypoint": "train.py"})
    _, reasons, signals = score(target, imported)
    assert signals == {"entrypoint": 1.0}
    assert reasons == ["same command train.py"]


def test_the_objective_ignores_params_and_system_metrics():
    a = _view({"metrics": {"val_loss": 1.0, "lr": 0.1, "sys_cpu_percent": 3.0},
               "params": {"lr": 0.1}})
    b = _view({"metrics": {"val_loss": 2.0, "acc": 0.5, "sys_rss_mb": 1.0}})
    _, reasons, signals = score(a, b)
    assert signals["objective"] == pytest.approx(1 / 2)
    assert "same metrics: val_loss" in reasons


def test_the_branch_is_equality_and_reads_a_features_branch_too():
    a = _view({"branch": "feat/x"})
    assert _signals(a, _view(features={"branch": "feat/x"})) == {"branch": 1.0}
    assert _signals(a, _view({"branch": "main"})) == {"branch": 0.0}


def test_signals_missing_on_either_side_are_left_out_not_counted_as_zero():
    target = {"row": run("a", params={"lr": 0.1}, branch="main"),
              "features": changed(files=["a.py"])}
    imported = _view({"params": {"lr": 0.1}})
    total, _, signals = score(target, imported)
    assert signals == {"params": 1.0}
    assert total == 1.0


def test_nothing_in_common_scores_zero_with_no_reasons():
    assert score(_view(), _view()) == (0.0, [], {})


def test_conf_weights_merge_over_the_defaults_and_bad_values_are_ignored():
    weights = resolve_weights({"params": 5, "bogus": 3, "code": -1, "files": "x", "branch": True})
    assert weights == dict(DEFAULT_WEIGHTS, params=5.0)


def test_weights_change_the_score():
    a = {"row": run("a", params={"opt": "adam"})}
    b = {"row": run("b", params={"opt": "sgd"})}
    assert score(a, b)[0] == pytest.approx(
        DEFAULT_WEIGHTS["code"] / (DEFAULT_WEIGHTS["code"] + DEFAULT_WEIGHTS["params"]))
    assert score(a, b, weights={"params": 0})[0] == 1.0
    assert score(a, b, weights={"code": 0})[0] == 0.0


def test_reasons_are_the_three_largest_contributions():
    features = changed(files=["a.py"], symbols=["a.py::f"])
    row = {"params": {"lr": 0.1}, "branch": "main", "metrics": {"acc": 1.0}}
    _, reasons, signals = score({"row": run("a", **row), "features": features},
                                {"row": run("b", **row), "features": features})
    assert len(signals) == 6
    assert reasons == ["1 shared function: a.py::f", "same base commit aaaaaaa",
                       "1 shared file: a.py"]


def test_the_text_signal_counts_only_with_a_text_score():
    assert "text" not in _signals(_view(), _view())
    total, reasons, signals = score(_view(), _view(), text_score=0.5, text_reason="shared: focal")
    assert signals == {"text": 0.5} and total == 0.5
    assert reasons == ["shared: focal"]


def test_an_intent_on_the_target_raises_the_default_text_weight():
    boosted = resolve_weights(intent=True)
    assert boosted["text"] == DEFAULT_WEIGHTS["code"] + DEFAULT_WEIGHTS["inputs"]
    assert resolve_weights({"text": 1}, intent=True)["text"] == 1.0
    plain = score({"row": run("a")}, {"row": run("b")}, text_score=0.0)[0]
    with_intent = score({"row": run("a"), "intent": {"text": "focal loss"}},
                        {"row": run("b")}, text_score=0.0)[0]
    assert with_intent < plain
