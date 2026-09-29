"""A sweep as one payload: spec, status summary and the attributed trials —
what ``vmn-exp ui`` serves at ``.../experiments/{verstr}/sweep``."""
from vmn_exp.core.sweep.summary import metric_value, stopped_early, summarize, trial_of


def sweep_view(spec, sweep_verstr, trials, claimed=()):
    """*trials* are :func:`~vmn_exp.core.sweep.summary.trial_rows`' rows."""
    return {
        "sweep": sweep_verstr,
        "spec": spec,
        "summary": dict(summarize(spec, trials, claimed), sweep=sweep_verstr),
        "trials": [_trial_entry(spec, row) for row in sorted(trials, key=trial_of)],
    }


def _trial_entry(spec, row):
    trial, attempt = trial_of(row)
    return {
        "verstr": row["verstr"],
        "name": row.get("name"),
        "trial": trial,
        "attempt": attempt,
        "status": row.get("status"),
        "params": row.get("params") or {},
        "value": metric_value(spec, row),
        "metric_source": row.get("metric_source", row["verstr"]),
        "stopped_early": stopped_early(row),
    }
