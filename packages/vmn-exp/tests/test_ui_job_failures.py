"""Plan 23 S3: a failure cluster's overrepresented params are the ones worth
a look: low-cardinality params (<= 20 distinct values in the job), carried
by at least max(5 runs, 10% of the cluster), at least 1.5x as common in the
cluster as in the job, at most 5 of them."""
from vmn_exp.ui.failure_signature import signature
from vmn_exp.ui.job_failures import failure_clusters


def _row(n, failed, **params):
    return {"verstr": f"v{n:05d}", "status": "failed" if failed else "succeeded",
            "exit_code": 1 if failed else 0, "params": params}


def _params(rows):
    counts = {}
    for row in rows:
        sig = signature(row)
        if sig:
            counts[sig] = counts.get(sig, 0) + 1
    (cluster,) = failure_clusters(counts, rows, 20)["clusters"]
    return cluster["params"]


def _job(failed, ok, failed_params, ok_params):
    return ([_row(i, True, **failed_params(i)) for i in range(failed)]
            + [_row(failed + i, False, **ok_params(i)) for i in range(ok)])


def test_a_strongly_overrepresented_param_is_reported_with_its_shares():
    rows = _job(10, 30, lambda i: {"opt": "big"}, lambda i: {"opt": "sgd" if i % 2 else "adam"})
    assert _params(rows) == [{"key": "opt", "value": "big", "share": 1.0, "base_share": 0.25}]


def test_a_high_cardinality_param_is_never_reported():
    # lr takes 21 distinct values across the job: continuous, not a cause.
    rows = _job(10, 30, lambda i: {"lr": 0.5}, lambda i: {"lr": i % 20 / 100})
    assert _params(rows) == []


def test_twenty_distinct_values_still_count_as_low_cardinality():
    rows = _job(10, 30, lambda i: {"lr": 0.5}, lambda i: {"lr": i % 19 / 100})
    assert [p["key"] for p in _params(rows)] == ["lr"]


def test_support_below_five_runs_is_not_reported():
    rows = _job(10, 30, lambda i: {"bs": 512 if i < 4 else 64}, lambda i: {"bs": 64})
    assert _params(rows) == []
    rows = _job(10, 30, lambda i: {"bs": 512 if i < 5 else 64}, lambda i: {"bs": 64})
    assert [(p["key"], p["value"]) for p in _params(rows)] == [("bs", 512)]


def test_support_below_ten_percent_of_a_large_cluster_is_not_reported():
    # 9 of 100 failed runs carry gpu=a100 (never in a success): under 10%.
    rows = _job(100, 100, lambda i: {"gpu": "a100" if i < 9 else "v100"},
                lambda i: {"gpu": "v100"})
    assert _params(rows) == []
    rows = _job(100, 100, lambda i: {"gpu": "a100" if i < 10 else "v100"},
                lambda i: {"gpu": "v100"})
    assert [(p["key"], p["value"]) for p in _params(rows)] == [("gpu", "a100")]


def test_a_lift_below_one_and_a_half_is_not_reported():
    # opt=big: 70% of the cluster vs 50% of the job (lift 1.4).
    rows = _job(10, 10, lambda i: {"opt": "big" if i < 7 else "sgd"},
                lambda i: {"opt": "big" if i < 3 else "sgd"})
    assert _params(rows) == []
    # 80% vs 50%: lift 1.6.
    rows = _job(10, 10, lambda i: {"opt": "big" if i < 8 else "sgd"},
                lambda i: {"opt": "big" if i < 2 else "sgd"})
    assert [(p["key"], p["value"]) for p in _params(rows)] == [("opt", "big")]


def test_at_most_five_params_are_reported():
    keys = [f"p{k}" for k in range(7)]
    rows = _job(10, 30, lambda i: dict.fromkeys(keys, "x"), lambda i: dict.fromkeys(keys, "y"))
    assert len(_params(rows)) == 5
