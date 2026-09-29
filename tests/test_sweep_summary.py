"""Sweep status: trial counts, the best trial per goal, bayes history."""
import math

from vmn_exp.core.sweep.spec import parse_spec
from vmn_exp.core.sweep.summary import best_trial, history, summarize


def _spec(goal="min", run_cap=None):
    data = {
        "method": "random",
        "metric": {"name": "loss", "goal": goal},
        "parameters": {"lr": {"distribution": "uniform", "min": 0.0, "max": 1.0}},
    }
    if run_cap:
        data["run_cap"] = run_cap
    return parse_spec(data)


def _row(trial, status, loss=None, lr=0.5, tags=None, attempt=0, verstr=None):
    all_tags = {"sweep_trial": str(trial), "sweep_attempt": str(attempt)}
    all_tags.update(tags or {})
    metrics = {} if loss is None else {"loss": loss}
    return {
        "verstr": verstr or f"v{trial}.{attempt}",
        "name": f"t{trial}",
        "status": status,
        "tags": all_tags,
        "params": {"lr": lr},
        "metrics": metrics,
    }


def test_best_trial_follows_the_goal():
    rows = [_row(0, "succeeded", 0.5), _row(1, "succeeded", 0.2), _row(2, "succeeded", 0.9)]
    assert best_trial(_spec("min"), rows)["verstr"] == "v1.0"
    assert best_trial(_spec("max"), rows)["verstr"] == "v2.0"


def test_best_trial_skips_missing_and_non_finite_metrics():
    rows = [_row(0, "running"), _row(1, "succeeded", math.nan), _row(2, "failed", 0.7)]
    assert best_trial(_spec(), rows)["verstr"] == "v2.0"
    assert best_trial(_spec(), [_row(0, "running")]) is None


def test_summary_counts_the_latest_attempt_of_each_trial():
    rows = [
        _row(0, "failed", attempt=0),
        _row(0, "succeeded", 0.3, attempt=1),
        _row(1, "running", 0.4),
        _row(2, "succeeded", 0.9, tags={"stopped_early": "true"}),
    ]
    claims = [{"trial": 0}, {"trial": 0, "attempt": 1}, {"trial": 1}, {"trial": 2}, {"trial": 3}]
    summary = summarize(_spec(run_cap=10), rows, claims)
    assert summary["counts"] == {"succeeded": 2, "running": 1}
    assert summary["stopped_early"] == 1
    assert summary["trials"] == 3
    assert summary["claimed"] == 4
    assert summary["unstarted"] == 1  # trial 3: claimed, its run never created
    assert summary["run_cap"] == 10
    assert summary["best"]["trial"] == 0
    assert summary["best"]["value"] == 0.3
    assert summary["best"]["params"] == {"lr": 0.5}


def test_history_is_finished_trials_with_a_value():
    rows = [
        _row(0, "succeeded", 0.3, lr=0.1),
        _row(1, "running", 0.2, lr=0.2),
        _row(2, "failed", lr=0.3),
        _row(3, "succeeded", 0.8, lr=0.4, tags={"stopped_early": "true"}),
    ]
    assert history(_spec(), rows) == [({"lr": 0.1}, 0.3), ({"lr": 0.4}, 0.8)]
