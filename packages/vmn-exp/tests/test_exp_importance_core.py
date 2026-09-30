"""Parameter importance (vmn_exp.core.importance): which params drive a metric."""
import random
import time

import pytest

from vmn_exp.core.importance import MAX_ROWS, param_importance, require_metric


def _row(i, metric, **params):
    return {"verstr": f"1.0.0-dev.r{i:05d}", "metrics": metric, "params": params}


def _synthetic(n=400, seed=1):
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        lr = rnd.uniform(0.0, 1.0)
        noise = rnd.uniform(0.0, 1.0)
        opt = rnd.choice(["adam", "sgd", "rmsprop"])
        bump = {"adam": 0.0, "sgd": 0.3, "rmsprop": 0.1}[opt]
        loss = 3.0 * lr + bump + rnd.gauss(0, 0.02)
        rows.append(_row(i, {"loss": loss}, lr=lr, noise=noise, opt=opt, const=7))
    return rows


def _by_param(result):
    return {entry["param"]: entry for entry in result}


def test_the_driving_param_ranks_first_and_noise_near_zero():
    result = param_importance(_synthetic(), "loss")
    assert result[0]["param"] == "lr"
    found = _by_param(result)
    assert found["lr"]["importance"] > 0.6
    assert found["noise"]["importance"] < 0.1
    assert found["lr"]["correlation"] > 0.9
    assert abs(found["noise"]["correlation"]) < 0.2
    assert found["lr"]["spearman"] > 0.9


def test_importances_are_sorted_and_sum_to_one():
    result = param_importance(_synthetic(), "loss")
    scores = [entry["importance"] for entry in result]
    assert scores == sorted(scores, reverse=True)
    assert sum(scores) == pytest.approx(1.0)


def test_a_categorical_param_is_scored_and_marked_categorical():
    found = _by_param(param_importance(_synthetic(), "loss"))
    assert found["opt"]["kind"] == "categorical"
    assert found["opt"]["correlation"] is None
    assert found["opt"]["importance"] > found["noise"]["importance"]
    assert found["lr"]["kind"] == "numeric"


def test_bools_are_zero_one():
    rows = [_row(i, {"acc": 1.0 if i % 2 else 0.0}, cache=bool(i % 2)) for i in range(40)]
    found = _by_param(param_importance(rows, "acc"))
    assert found["cache"]["kind"] == "bool"
    assert found["cache"]["correlation"] == pytest.approx(1.0)
    assert found["cache"]["importance"] == pytest.approx(1.0)


def test_single_valued_params_are_skipped():
    assert "const" not in _by_param(param_importance(_synthetic(), "loss"))


def test_n_counts_the_runs_carrying_the_param_and_the_metric():
    rows = _synthetic(100)
    for row in rows[:30]:
        del row["params"]["noise"]
    rows.append(_row(999, {}, lr=0.5, noise=0.5))  # no metric: not counted
    found = _by_param(param_importance(rows, "loss"))
    assert found["lr"]["n"] == 100
    assert found["noise"]["n"] == 70


def test_the_target_itself_is_not_a_param():
    rows = [_row(i, {"lr": i / 10}, lr=i / 10, other=i % 3) for i in range(30)]
    assert "lr" not in _by_param(param_importance(rows, "lr"))


def test_no_rows_with_the_metric_yields_nothing():
    assert param_importance([], "loss") == []
    assert param_importance([_row(0, {"acc": 1}, lr=1)], "loss") == []


def test_the_result_is_deterministic_and_order_independent():
    rows = _synthetic()
    first = param_importance(rows, "loss")
    shuffled = list(rows)
    random.Random(5).shuffle(shuffled)
    assert param_importance(shuffled, "loss") == first


def test_rows_beyond_the_cap_are_sampled_deterministically():
    rows = _synthetic(300)
    result = param_importance(rows, "loss", max_rows=120)
    assert _by_param(result)["lr"]["n"] == 120
    assert param_importance(rows, "loss", max_rows=120) == result
    assert MAX_ROWS == 5000


def test_require_metric_rejects_a_metric_no_run_carries():
    rows = _synthetic(10)
    require_metric(rows, "loss")
    with pytest.raises(ValueError, match="nope"):
        require_metric(rows, "nope")


def test_five_thousand_runs_by_thirty_params_is_fast():
    rnd = random.Random(3)
    rows = []
    for i in range(6000):
        params = {f"p{k}": rnd.random() for k in range(27)}
        params.update(opt=rnd.choice("abcde"), flag=rnd.random() < 0.5, width=rnd.choice([32, 64]))
        rows.append(_row(i, {"loss": params["p0"] * 2 + rnd.random() * 0.1}, **params))
    start = time.perf_counter()
    result = param_importance(rows, "loss")
    elapsed = time.perf_counter() - start
    assert result[0]["param"] == "p0"
    assert len(result) == 30
    assert elapsed < 1.5, elapsed
