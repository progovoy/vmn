#!/usr/bin/env python3
"""A job's rollup as JSON, from the :class:`~vmn_exp.ui.job_tally.Tally`
parts its subtree is split into (static rows and live overlay, per nested
job): read side by side, never merged into one tally."""
from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.failure_signature import label
from vmn_exp.ui.job_tally import DONE, STATES, higher_first

THROUGHPUT_WINDOW_MIN = 10
HIST_BINS = 20
SPREAD_BINS = 12
TOP_FAILURES = 10


def _expected(job, total):
    """The sweep's planned size, else ``params.expected_pods``, else the runs so far."""
    if job.get("sweep_planned") is not None:
        return job["sweep_planned"]
    pods = (job.get("params") or {}).get("expected_pods")
    return int(pods) if is_finite_number(pods) and pods > 0 else total


def _counts(parts):
    counts = dict.fromkeys(STATES.values(), 0)
    for part in parts:
        for status, count in part.counts.items():
            if status in STATES:
                counts[STATES[status]] += count
    return counts


def _edge(parts, field, pick):
    stamps = [getattr(part, field)[0] for part in parts if getattr(part, field)]
    return pick(stamps) if stamps else None


def progress_fields(job, parts, now):
    """Counts, size, progress, throughput, ETA and time span."""
    counts = _counts(parts)
    total = sum(counts.values())
    done = sum(counts[STATES[s]] for s in DONE)
    expected = _expected(job, total)
    now_minute = int(now.timestamp() // 60)
    recent = sum(p.completions.recent(now_minute, THROUGHPUT_WINDOW_MIN) for p in parts)
    throughput = recent / THROUGHPUT_WINDOW_MIN
    left = max(expected - done, 0)
    eta = 0 if not left else (round(left / throughput * 60) if throughput else None)
    return {
        "verstr": job["verstr"], "total": total, "counts": counts, "done": done,
        "expected": expected,
        "progress": round(min(done / expected, 1.0), 4) if expected else None,
        "failed_pct": round(100 * counts["failed"] / total, 2) if total else 0.0,
        "throughput_per_min": throughput, "eta_sec": eta,
        "started_at": _edge(parts, "started", min),
        "finished_at": _edge(parts, "finished", max),
    }


def _merged(sketches):
    if len(sketches) == 1:
        return sketches[0]
    out = sketches[0].copy()
    for sketch in sketches[1:]:
        out.merge(sketch)
    return out


def _significant(value):
    """*value* without the float noise sums carried by additions and removals pick up."""
    return float(f"{value:.12g}")


def _metric_parts(parts, name):
    return [p.metrics[name] for p in parts if name in p.metrics]


def _highest(tallies):
    high = tallies[0].high[0]
    for tally in tallies[1:]:
        if higher_first(tally.high[0], high):
            high = tally.high[0]
    return high


def metric_fields(parts, name, descending, bins=HIST_BINS):
    """One tracked metric over the subtree, or None when no run carries it."""
    tallies = _metric_parts(parts, name)
    if not tallies:
        return None
    n = sum(t.n for t in tallies)
    low = min(t.low[0] for t in tallies)
    high = _highest(tallies)
    best = high if descending else low
    sketch = _merged([t.sketch for t in tallies])
    return {
        "n": n, "min": low[0], "max": high[0], "mean": _significant(sum(t.total for t in tallies) / n),
        "best": best[0], "best_verstr": best[1],
        "p10": sketch.quantile(0.1), "p50": sketch.quantile(0.5), "p90": sketch.quantile(0.9),
        "hist": sketch.histogram(bins=bins, lo=low[0], hi=high[0]),
    }


def _failures(parts):
    counts = {}
    for part in parts:
        for sig, count in part.failures.items():
            counts[sig] = counts.get(sig, 0) + count
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_FAILURES]
    return [{"sig": sig, "label": label(sig), "count": count} for sig, count in top]


def job_payload(job, parts, spec, now):
    """The full rollup of the job whose row is *job*."""
    duration = _merged([p.duration for p in parts]) if parts else None
    return {
        **progress_fields(job, parts, now),
        "metrics": {m: metric_fields(parts, m, spec.descending[m]) for m in spec.metrics},
        "duration": {
            "n": duration.count if duration else 0,
            "p50": duration.quantile(0.5) if duration else None,
            "p90": duration.quantile(0.9) if duration else None,
        },
        "failures": _failures(parts),
    }


def job_summary(job, parts, spec, now):
    """The compact rollup a Jobs view sorts on: progress, plus the main
    metric's best and a spread histogram (counts only)."""
    main = spec.main and metric_fields(parts, spec.main, spec.descending[spec.main],
                                       bins=SPREAD_BINS)
    return {
        **progress_fields(job, parts, now),
        "metric": spec.main,
        "best": main["best"] if main else None,
        "best_verstr": main["best_verstr"] if main else None,
        "spread": [b["count"] for b in main["hist"]] if main else [],
    }
