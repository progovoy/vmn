"""A sweep's trials as rows, and ``vmn-exp sweep status`` folded from them.

A trial row is an ordinary run row (status-annotated) whose ``parent`` is the
sweep; its ``sweep_trial`` / ``sweep_attempt`` tags say which slot it fills.
A retried trial is judged by its latest attempt. An early-stopped trial ends
``succeeded`` and carries the tag ``stopped_early=true``.

A trial's target metric is its own when it logged one, else its descendants'
(a ``start_run()`` inside the trial nests a run under it): the only descendant
carrying the metric, or the best of several by goal. ``metric_source`` names
the run it came from, so the median rule reads that run's series.
"""
from collections import Counter

from vmn_exp.core import index as experiment_index
from vmn_exp.core.log import _sortable
from vmn_exp.core.status import FAILED, STUCK, SUCCEEDED
from vmn_exp.core.tree import annotate_rows, children_by_parent, subtree_verstrs

STOPPED_EARLY_TAG = "stopped_early"
RETRYABLE = (FAILED, STUCK)


def trial_rows(storage, app_name, sweep_verstr, spec):
    """Every run of the sweep (retries included), status-annotated, with the
    target metric attributed (see :func:`attribute_metric`)."""
    rows, run_states, observed = experiment_index.indexed_status_rows(storage, app_name)
    return sweep_trials(spec, sweep_verstr, rows, run_states, observed)


def sweep_trials(spec, sweep_verstr, rows, run_states, observed=None):
    """:func:`trial_rows` over rows the caller already holds (``vmn-exp ui``
    answers from its own index snapshot)."""
    annotated = annotate_rows(rows, run_states, observed)
    trials = [r for r in annotated if r.get("parent") == sweep_verstr]
    return attribute_metric(spec, trials, annotated)


def attribute_metric(spec, trials, rows):
    """Copies of *trials* carrying ``metric_source`` and, when a descendant in
    *rows* supplied it, the target metric in ``metrics``."""
    name = spec["metric"]["name"]
    children_of = children_by_parent(rows)
    by_verstr = {r["verstr"]: r for r in rows}
    attributed = []
    for trial in trials:
        source = _metric_source(spec, trial, children_of, by_verstr)
        row = dict(trial, metric_source=source["verstr"])
        if source is not trial:
            row["metrics"] = dict(trial.get("metrics") or {}, **{name: metric_value(spec, source)})
        attributed.append(row)
    return attributed


def _metric_source(spec, trial, children_of, by_verstr):
    if metric_value(spec, trial) is not None:
        return trial
    descendants = [by_verstr[v] for v in subtree_verstrs(trial["verstr"], children_of)
                   if v != trial["verstr"] and v in by_verstr]
    return best_trial(spec, descendants) or trial


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
    return value if _sortable(value) else None


def best_trial(spec, rows):
    """The row with the best finite target metric, or None."""
    scored = [(v, r) for v, r in ((metric_value(spec, r), r) for r in rows) if v is not None]
    if not scored:
        return None
    pick = min if spec["metric"]["goal"] == "min" else max
    return pick(scored, key=lambda pair: pair[0])[1]


def history(spec, rows):
    """``[(params, value)]`` of the succeeded trials — what bayes learns from."""
    finished = ((r.get("params") or {}, metric_value(spec, r))
                for r in rows if r.get("status") == SUCCEEDED)
    return [(params, value) for params, value in finished if value is not None]


def retry_slots(rows):
    """``[(trial, next attempt)]`` of the trials whose latest attempt failed
    or got stuck (and was not stopped early)."""
    return sorted(
        (trial, trial_of(row)[1] + 1) for trial, row in latest_attempts(rows).items()
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
