#!/usr/bin/env python3
"""A job's rollup as JSON, from the :class:`~vmn_exp.ui.job_tally.Tally`
parts its subtree is split into (static rows and live overlay, per nested
job): read side by side, never merged into one tally."""
from collections import Counter

from vmn_exp.core.values import is_finite_number
from vmn_exp.ui.failure_signature import label
from vmn_exp.ui.job_tally import DONE, STATES, higher_first
from vmn_exp.ui.job_timeline import timeline
from vmn_exp.ui.quantile_sketch import QuantileSketch

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


def metric_fields(parts, name, descending, bins=HIST_BINS, quantiles=True, ranked=True):
    """One tracked metric over the subtree, or None when no run carries it;
    a goal-less one (not *ranked*) has no best."""
    tallies = _metric_parts(parts, name)
    if not tallies:
        return None
    n = sum(t.n for t in tallies)
    low = min(t.low[0] for t in tallies)
    high = _highest(tallies)
    best = (high if descending else low) if ranked else (None, None)
    sketch = _merged([t.sketch for t in tallies])
    fields = {
        "n": n, "min": low[0], "max": high[0], "mean": _significant(sum(t.total for t in tallies) / n),
        "best": best[0], "best_verstr": best[1],
        "hist": sketch.histogram(bins=bins, lo=low[0], hi=high[0]),
    }
    if quantiles:
        fields.update(zip(("p10", "p50", "p90"), sketch.quantiles([0.1, 0.5, 0.9])))
    return fields


def failure_counts(parts):
    """``{failure signature: runs}`` over the job's subtree."""
    counts = Counter()
    for part in parts:
        counts.update(part.failures)
    return dict(counts)


def _failures(parts):
    counts = failure_counts(parts)
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_FAILURES]
    return [{"sig": sig, "label": label(sig), "count": count} for sig, count in top]


def job_payload(job, parts, spec, now):
    """The full rollup of the job whose row is *job*."""
    duration = _merged([p.duration for p in parts]) if parts else QuantileSketch()
    p50, p90 = duration.quantiles([0.5, 0.9])
    return {
        **progress_fields(job, parts, now),
        "metric": spec.main, "ranked": spec.ranked,
        "metrics": {m: metric_fields(parts, m, spec.descending[m], ranked=spec.ranked)
                    for m in spec.metrics},
        "duration": {"n": duration.count, "p50": p50, "p90": p90},
        "failures": _failures(parts),
        "timeline": timeline(parts),
    }


def job_summary(job, parts, spec, now, idx_of=None):
    """The compact rollup a Jobs view sorts on: progress, plus the main
    metric's best (its ``idx`` from *idx_of(verstr)*) and a spread
    histogram (counts only)."""
    main = spec.main and metric_fields(parts, spec.main, spec.descending[spec.main],
                                       bins=SPREAD_BINS, quantiles=False, ranked=spec.ranked)
    main = main or {}
    return {
        **progress_fields(job, parts, now),
        "metric": spec.main,
        "best": main.get("best"),
        "best_verstr": main.get("best_verstr"),
        "best_idx": idx_of(main["best_verstr"]) if idx_of and main.get("best_verstr") else None,
        "spread": [b["count"] for b in main.get("hist", ())],
    }
