"""Rerun identity in similar runs (vmn_exp.core.similar): a run's code, params
and inputs. The target's reruns are left out and the reruns of one config fill
one slot; runs of the same clean code with other params or inputs are
ordinary candidates, each config its own slot."""
from similar_fixtures import FakeSnapshot, dataset, run, verstrs
from vmn_exp.core.similar import similar_runs

CLEAN = "1.0.0-dev.aaaaaaa.0000000"


def _target(row):
    return {"row": row, "features": None, "intent": None, "hypothesis": None,
            "text": None, "text_only": False}


def _clean(verstr, **fields):
    return run(verstr, code=CLEAN, **fields)


def _found(rows, target):
    return similar_runs(FakeSnapshot(rows), _target(target), top=20)


def test_a_sibling_with_other_params_on_the_same_clean_code_is_returned():
    target = _clean("t", params={"lr": 0.001, "optimizer": "adam"})
    sibling = _clean("s", params={"lr": 0.01, "optimizer": "adam"})
    assert verstrs(_found([target, sibling], target)) == ["s"]


def test_a_sibling_with_other_inputs_on_the_same_clean_code_is_returned():
    params = {"lr": 0.001}
    target = _clean("t", params=params, inputs=dataset("imagenet", "sha256:a"))
    sibling = _clean("s", params=params, inputs=dataset("imagenet", "sha256:b"))
    assert verstrs(_found([target, sibling], target)) == ["s"]


def test_an_exact_rerun_of_the_target_is_left_out():
    params = {"lr": 0.001}
    target = _clean("t", params=params, inputs=dataset("imagenet", "sha256:a"))
    rows = [target, _clean("again", params=dict(params), inputs=dataset("imagenet", "sha256:a")),
            _clean("other", params={"lr": 0.1})]
    assert verstrs(_found(rows, target)) == ["other"]


def test_params_compare_exactly():
    target = _clean("t", params={"lr": 1})
    rows = [target, _clean("as_text", params={"lr": "1"}), _clean("more", params={"lr": 1, "x": 0})]
    assert sorted(verstrs(_found(rows, target))) == ["as_text", "more"]


def test_params_json_cannot_sort_still_tell_reruns_apart():
    target = _clean("t", params={"grid": {1: "a", "b": 2}})
    rows = [target, _clean("again", params={"grid": {1: "a", "b": 2}}),
            _clean("other", params={"grid": {1: "a", "b": 3}})]
    assert verstrs(_found(rows, target)) == ["other"]


def test_a_fork_of_the_target_with_its_params_is_still_returned():
    params = {"lr": 0.001}
    target = _clean("t", params=params)
    fork = _clean("fork", params=dict(params), forked_from="t")
    assert verstrs(_found([target, fork], target)) == ["fork"]


def test_the_run_the_target_forked_from_is_still_returned():
    params = {"lr": 0.001}
    source = _clean("source", params=params)
    target = _clean("t", params=dict(params), forked_from="source")
    assert verstrs(_found([source, target], target)) == ["source"]


def test_two_reruns_of_another_config_fill_one_slot():
    target = _clean("t", params={"lr": 0.001})
    rows = [target, _clean("seed1", params={"lr": 0.01}), _clean("seed2", params={"lr": 0.01})]
    [item] = _found(rows, target)
    assert item["verstr"] in ("seed1", "seed2") and item["group_size"] == 2


def test_two_configs_on_the_same_commit_are_two_slots():
    target = _clean("t", params={"lr": 0.001})
    rows = [target, _clean("a", params={"lr": 0.01}), _clean("b", params={"lr": 0.1})]
    items = _found(rows, target)
    assert sorted(verstrs(items)) == ["a", "b"]
    assert [i["group_size"] for i in items] == [1, 1]


def test_reruns_of_one_config_on_other_code_are_two_slots():
    params = {"lr": 0.01}
    target = _clean("t", params={"lr": 0.001})
    rows = [target, _clean("a", params=params), run("b", params=dict(params))]
    assert sorted(verstrs(_found(rows, target))) == ["a", "b"]


def test_the_target_tree_is_still_left_out_and_a_tree_still_fills_one_slot():
    params = {"lr": 0.1}
    rows = [
        _clean("outer", params={}),
        _clean("t", parent="outer", params=params),
        _clean("trial", parent="outer", params={"lr": 0.2}),
        _clean("sweep", params={}),
        _clean("s1", parent="sweep", params={"lr": 0.3}),
        _clean("s2", parent="sweep", params={"lr": 0.4}),
    ]
    [item] = _found(rows, rows[1])
    assert item["verstr"] in ("s1", "s2") and item["group_size"] == 3


def test_a_working_tree_target_excludes_nothing():
    params = {"lr": 0.001}
    rows = [_clean("a", params=params)]
    working_tree = {"code_verstr": CLEAN, "params": dict(params)}
    assert verstrs(_found(rows, working_tree)) == ["a"]


def test_a_closer_config_on_the_same_commit_ranks_first():
    target = _clean("t", params={"lr": 0.001, "optimizer": "adam", "bs": 32})
    rows = [target,
            _clean("near", params={"lr": 0.002, "optimizer": "adam", "bs": 32}),
            _clean("far", params={"lr": 0.5, "optimizer": "sgd", "bs": 256})]
    items = _found(rows, target)
    assert verstrs(items) == ["near", "far"]
    assert items[0]["score"] > items[1]["score"]
