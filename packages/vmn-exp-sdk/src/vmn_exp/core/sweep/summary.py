"""A sweep's trials as rows, and ``vmn-exp sweep status`` folded from them.

A trial row is an ordinary run row (status-annotated) whose ``parent`` is the
sweep; its ``sweep_trial`` / ``sweep_attempt`` tags say which slot it fills.
A retried trial is judged by its latest attempt. An early-stopped trial ends
``succeeded`` and carries the tag ``stopped_early=true``.
"""
import math
from collections import Counter

from vmn_exp.core import index as experiment_index
from vmn_exp.core.status import FAILED, STUCK, SUCCEEDED
from vmn_exp.core.tree import annotate_rows

STOPPED_EARLY_TAG = "stopped_early"
RETRYABLE = (FAILED, STUCK)


def trial_rows(storage, app_name, sweep_verstr):
    """Every run of the sweep (retries included), status-annotated."""
    rows, run_states, observed = experiment_index.indexed_status_rows(storage, app_name)
    annotated = annotate_rows(rows, run_states, observed)
    return [r for r in annotated if r.get("parent") == sweep_verstr]


def trial_of(row):
    tags = row.get("tags") or {}
    return int(tags.get("sweep_trial", -1)), int(tags.get("sweep_attempt", 0))


def latest_attempts(rows):
    """``{trial: row}`` of each trial's latest attempt."""
    latest = {}
    for row in sorted(rows, key=trial_of):
        latest[trial_of(row)[0]] = row
    return latest


def stopped_early(row):
    return (row.get("tags") or {}).get(STOPPED_EARLY_TAG) == "true"


def metric_value(spec, row):
    value = (row.get("metrics") or {}).get(spec["metric"]["name"])
    ok = isinstance(value, (int, float)) and math.isfinite(value)
    return value if ok else None


def best_trial(spec, rows):
    """The row with the best finite target metric, or None."""
    scored = [(metric_value(spec, r), r) for r in rows]
    scored = [(v, r) for v, r in scored if v is not None]
    if not scored:
        return None
    pick = min if spec["metric"]["goal"] == "min" else max
    return pick(scored, key=lambda pair: pair[0])[1]


def history(spec, rows):
    """``[(params, value)]`` of the succeeded trials — what bayes learns from."""
    finished = [r for r in rows if r.get("status") == SUCCEEDED]
    return [(r.get("params") or {}, metric_value(spec, r)) for r in finished
            if metric_value(spec, r) is not None]


def retryable_trials(rows):
    """Trial indices whose latest attempt failed or got stuck (not stopped early)."""
    return sorted(
        trial for trial, row in latest_attempts(rows).items()
        if row.get("status") in RETRYABLE and not stopped_early(row)
    )


def summarize(spec, rows, claims=()):
    latest = latest_attempts(rows)
    claimed = {c["trial"] for c in claims}
    best = best_trial(spec, list(latest.values()))
    return {
        "method": spec["method"],
        "metric": spec["metric"],
        "run_cap": spec.get("run_cap"),
        "trials": len(latest),
        "claimed": len(claimed),
        "unstarted": len(claimed - set(latest)),
        "counts": dict(Counter(r.get("status") for r in latest.values())),
        "stopped_early": sum(stopped_early(r) for r in latest.values()),
        "best": None if best is None else {
            "verstr": best["verstr"],
            "name": best.get("name"),
            "trial": trial_of(best)[0],
            "value": metric_value(spec, best),
            "params": best.get("params") or {},
        },
    }
