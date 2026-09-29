"""A sweep's trials as rows, and ``vmn-exp sweep status`` folded from them.

A trial row is an ordinary run row (status-annotated) whose ``parent`` is the
sweep; its ``sweep_trial`` / ``sweep_attempt`` tags say which slot it fills.
A retried trial is judged by its latest attempt. An early-stopped trial ends
``succeeded``, its run state's ``end_reason`` ``stopped``.

A trial's target metric is its own when it logged one, else its descendants'
(a ``start_run()`` inside the trial nests a run under it): the only descendant
carrying the metric, or the best of several by goal. ``metric_source`` names
the run it came from, so the median rule reads that run's series.
"""
import weakref
from collections import Counter

from vmn_exp.core import index as experiment_index
from vmn_exp.core.values import is_finite_number
from vmn_exp.core.status import FAILED, STOPPED, STUCK, SUCCEEDED
from vmn_exp.core.tree import annotate_rows, children_by_parent, subtree_verstrs

RETRYABLE = (FAILED, STUCK)
_CHILDREN = weakref.WeakKeyDictionary()  # IndexSnapshot -> {parent: [child]}


def trial_rows(storage, app_name, sweep_verstr, spec, wait=True):
    """Every run of the sweep (retries included), status-annotated, with the
    target metric attributed (see :func:`attribute_metric`). *wait*: refresh
    the app's index first; False takes the current snapshot as is."""
    snap = experiment_index.indexed_snapshot(storage, app_name, wait=wait)
    return snapshot_trials(spec, sweep_verstr, snap)


def snapshot_trials(spec, sweep_verstr, snap):
    """:func:`trial_rows` off an index snapshot. Only the sweep's subtree is
    copied and annotated; the snapshot's parent map is built once per snapshot."""
    members = (snap.row(v) for v in subtree_verstrs(sweep_verstr, snapshot_children(snap)))
    annotated = annotate_rows(
        [row for row in members if row is not None],
        snap.run_states, snap.run_state_observed_at,
    )
    trials = [r for r in annotated if r.get("parent") == sweep_verstr]
    return attribute_metric(spec, trials, annotated)


def snapshot_children(snap):
    """``{parent: [child]}`` of *snap*'s edges, memoized per snapshot."""
    children_of = _CHILDREN.get(snap)
    if children_of is None:
        edges = ({"verstr": v, "parent": p} for v, p in snap.edges.items())
        children_of = _CHILDREN[snap] = children_by_parent(edges)
    return children_of


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
    return row.get("end_reason") == STOPPED


def metric_value(spec, row):
    value = (row.get("metrics") or {}).get(spec["metric"]["name"])
    return value if is_finite_number(value) else None


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


def summarize(spec, rows, claimed=()):
    """*claimed* is :func:`~vmn_exp.core.sweep.claims.claimed_trials`' set."""
    latest = latest_attempts(rows)
    claimed = set(claimed)
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
